/*
 * static/js/e2ee/vz-e2ee.mjs
 * ──────────────────────────
 * Chiffrement de bout en bout du chat privé de Vazimba, dans le navigateur.
 *
 * Le moteur est celui de Matrix / Element (matrix-sdk-crypto-wasm, construit sur vodozemac) :
 * Olm d'appareil à appareil, Megolm pour les messages d'une conversation. Les clés SECRÈTES
 * restent dans cet appareil (base IndexedDB du navigateur) ; le serveur de Vazimba ne reçoit que
 * des clés publiques et des contenus chiffrés (voir e2ee/views.py).
 *
 * Utilisation :
 *   const e2ee = await VazimbaE2EE.open({ userPk: 42, csrf: '…' });
 *   const chiffré = await e2ee.encrypt(roomPk, autrePk, { body: 'Salut' });
 *   const { content } = await e2ee.decrypt(roomPk, { id, senderPk, ts, ciphertext: chiffré });
 *   await e2ee.setupRecovery('mon code secret');   // sauvegarde des clés
 *   await e2ee.unlock('mon code secret');          // sur un nouvel appareil
 */
import * as M from '../../vendor/matrix-sdk-crypto-wasm-19.0.1/index.mjs';

const API = '/e2ee/';
const SERVER = 'vazimba.io';
const BACKUP_ALGORITHM = 'm.megolm_backup.v1.curve25519-aes-sha2';
const PBKDF2_ITERATIONS = 600000;     // (recommandation OWASP pour PBKDF2-SHA256)

const mx = (pk) => `@${pk}:${SERVER}`;
const roomOf = (pk) => `!${pk}:${SERVER}`;

// ── Petits outils ──────────────────────────────────────────────────────────

function store(key, value) {
    try {
        if (value === undefined) return localStorage.getItem(key);
        localStorage.setItem(key, String(value));
    } catch (e) { /* stockage indisponible (navigation privée stricte) */ }
    return null;
}

function randomId(length = 10) {
    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const bytes = crypto.getRandomValues(new Uint8Array(length));
    return Array.from(bytes, (b) => letters[b % 26]).join('');
}

const b64 = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)));
const unb64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

export class E2EEError extends Error {
    constructor(code, message) { super(message); this.code = code; }
}

// ── Le moteur d'un appareil ────────────────────────────────────────────────

export class VazimbaE2EE {
    /** Ouvre (ou crée, la première fois) le moteur de cet appareil pour ce membre. */
    static async open({ userPk, csrf, deviceName = '' }) {
        await M.initAsync();
        const keyOfDevice = `vz-e2ee-device:${userPk}`;
        let deviceId = store(keyOfDevice);
        if (!deviceId) {
            deviceId = 'VZ' + randomId(10);
            store(keyOfDevice, deviceId);
        }
        const machine = await M.OlmMachine.initialize(
            new M.UserId(mx(userPk)), new M.DeviceId(deviceId), `vz-e2ee:${userPk}`);
        const self = new VazimbaE2EE(machine, userPk, deviceId, csrf);
        await self._serial(() => self._outgoing());     // publier les clés de l'appareil
        await self._restoreBackupSettings();
        await self.sync();
        return self;
    }

    constructor(machine, userPk, deviceId, csrf) {
        this.machine = machine;
        this.userPk = userPk;
        this.deviceId = deviceId;
        this.csrf = csrf;
        this._queue = Promise.resolve();
    }

    /** L'empreinte de cet appareil (clé ed25519), pour la vérification des contacts. */
    get fingerprint() { return this.machine.identityKeys.ed25519.toBase64(); }

    // Une seule opération à la fois : le moteur et la boîte aux lettres ne supportent pas d'être
    // utilisés par deux demandes en même temps (deux messages envoyés vite, par exemple).
    _serial(fn) {
        const run = this._queue.then(fn, fn);
        this._queue = run.catch(() => {});
        return run;
    }

    async _fetch(method, path, body) {
        const response = await fetch(API + path, {
            method,
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrf,
                'X-E2EE-Device': this.deviceId,
            },
            body: body === undefined ? undefined : body,
        });
        const text = await response.text();
        if (!response.ok) {
            let errcode = 'M_UNKNOWN';
            try { errcode = JSON.parse(text).errcode || errcode; } catch (e) { /* */ }
            throw new E2EEError(errcode, `${method} ${path} : ${response.status}`);
        }
        return text;
    }

    // ── Ce que le moteur demande d'envoyer au serveur ────────────────────────

    async _send(request) {
        const T = M.RequestType;
        let text;
        switch (request.type) {
            case T.KeysUpload:      text = await this._fetch('POST', 'keys/upload', request.body); break;
            case T.KeysQuery:       text = await this._fetch('POST', 'keys/query', request.body); break;
            case T.KeysClaim:       text = await this._fetch('POST', 'keys/claim', request.body); break;
            case T.SignatureUpload: text = await this._fetch('POST', 'keys/signatures/upload', request.body); break;
            case T.ToDevice:
                text = await this._fetch('PUT', `sendToDevice/${encodeURIComponent(request.event_type)}/`
                                                + encodeURIComponent(request.txn_id), request.body);
                break;
            case T.KeysBackup:
                text = await this._fetch('PUT', `room_keys/keys?version=${encodeURIComponent(request.version)}`,
                                         request.body);
                break;
            default:
                return;    // (vérification dans une conversation Matrix : pas utilisée par Vazimba)
        }
        await this.machine.markRequestAsSent(request.id, request.type, text);
    }

    async _outgoing() {
        for (const request of await this.machine.outgoingRequests()) {
            await this._send(request);
        }
    }

    // ── Boîte aux lettres ────────────────────────────────────────────────────

    /** Relève la boîte aux lettres de l'appareil (clés de conversation reçues, nouveaux
     *  appareils des contacts), puis envoie ce que le moteur a en attente. */
    sync() { return this._serial(() => this._sync()); }

    async _sync() {
        const keySince = `vz-e2ee-since:${this.userPk}:${this.deviceId}`;
        const keyAck = `vz-e2ee-ack:${this.userPk}:${this.deviceId}`;
        let more = true;
        while (more) {
            const since = store(keySince) || 0;
            const ack = store(keyAck) || 0;
            const data = JSON.parse(await this._fetch('GET', `sync?since=${since}&ack=${ack}`));
            await this.machine.receiveSyncChanges(
                JSON.stringify(data.to_device.events),
                new M.DeviceLists(data.device_lists.changed.map((u) => new M.UserId(u)), []),
                new Map(Object.entries(data.device_one_time_keys_count)),
                new Set(data.device_unused_fallback_key_types),
            );
            store(keyAck, data.ack);          // (effacés du serveur à la relève suivante)
            store(keySince, data.since);
            more = data.more;
        }
        await this._outgoing();
        await this._backup();
    }

    // ── Messages ─────────────────────────────────────────────────────────────

    /** Chiffre `content` (objet) pour la conversation `roomPk` avec `otherPk`. Rend le texte
     *  chiffré à envoyer au serveur à la place du message. */
    encrypt(roomPk, otherPk, content) {
        return this._serial(async () => {
            await this._sync();
            const room = new M.RoomId(roomOf(roomPk));
            // (une liste donnée au moteur est consommée par lui : on en refait une à chaque appel)
            const users = () => [mx(otherPk), mx(this.userPk)].map((u) => new M.UserId(u));
            await this.machine.updateTrackedUsers(users());
            await this._outgoing();                               // clés des appareils des deux
            const claim = await this.machine.getMissingSessions(users());
            if (claim) await this._send(claim);                   // ouvrir les sessions Olm
            const settings = new M.EncryptionSettings();
            for (const request of await this.machine.shareRoomKey(room, users(), settings)) {
                await this._send(request);                        // clé de conversation, chiffrée
            }
            const ciphertext = await this.machine.encryptRoomEvent(room, 'm.room.message', JSON.stringify(content));
            await this._backup();
            return ciphertext;
        });
    }

    /** Déchiffre un message. `message` = { id, senderPk, ts (ms), ciphertext }.
     *  Rend { content, senderDevice } ; lève E2EEError('MISSING_KEY') si la clé manque. */
    async decrypt(roomPk, message) {
        const event = JSON.stringify({
            type: 'm.room.encrypted',
            event_id: `$vz${message.id}`,
            sender: mx(message.senderPk),
            origin_server_ts: message.ts,
            room_id: roomOf(roomPk),
            content: JSON.parse(message.ciphertext),
        });
        const attempt = async () => {
            // (objets neufs à chaque essai : le moteur peut garder ceux qu'on lui donne)
            const decrypted = await this.machine.decryptRoomEvent(
                event, new M.RoomId(roomOf(roomPk)), new M.DecryptionSettings(M.TrustRequirement.Untrusted));
            return {
                content: JSON.parse(decrypted.event).content,
                senderDevice: decrypted.senderDevice ? decrypted.senderDevice.toString() : '',
            };
        };
        try {
            return await attempt();
        } catch (first) {
            // La clé est peut-être arrivée dans la boîte aux lettres, ou dans la sauvegarde.
            await this.sync();
            try { return await attempt(); } catch (e) { /* */ }
            if (await this._restoreFromBackup()) {
                try { return await attempt(); } catch (e) { /* */ }
            }
            throw new E2EEError('MISSING_KEY', 'Clé de ce message introuvable sur cet appareil.');
        }
    }

    // ── Fichiers ─────────────────────────────────────────────────────────────

    /** Chiffre un fichier (Uint8Array). Rend { data, info } : `data` à envoyer au serveur,
     *  `info` (clé du fichier) à mettre DANS le message chiffré. */
    static encryptFile(bytes) {
        const encrypted = M.Attachment.encrypt(bytes);
        const info = encrypted.mediaEncryptionInfo;   // (lisible une seule fois)
        return { data: encrypted.encryptedData, info };
    }

    static decryptFile(data, info) {
        return M.Attachment.decrypt(new M.EncryptedAttachment(data, info));
    }

    // ── Sauvegarde des clés par code secret ──────────────────────────────────

    async _restoreBackupSettings() {
        const keys = await this.machine.getBackupKeys();
        if (keys.decryptionKey && keys.backupVersion) {
            await this.machine.enableBackupV1(keys.decryptionKey.megolmV1PublicKey.publicKeyBase64, keys.backupVersion);
        }
    }

    async _backup() {
        if (!(await this.machine.isBackupEnabled())) return;
        for (let i = 0; i < 20; i++) {           // (par paquets ; 20 paquets au plus à la fois)
            const request = await this.machine.backupRoomKeys();
            if (!request) return;
            await this._send(request);
        }
    }

    async _restoreFromBackup() {
        const keys = await this.machine.getBackupKeys();
        if (!keys.decryptionKey || !keys.backupVersion) return false;
        let data;
        try {
            data = JSON.parse(await this._fetch('GET', `room_keys/keys?version=${encodeURIComponent(keys.backupVersion)}`));
        } catch (e) { return false; }
        const rooms = new Map();
        for (const [roomId, room] of Object.entries(data.rooms || {})) {
            const sessions = new Map();
            for (const [sessionId, backed] of Object.entries(room.sessions || {})) {
                const s = backed.session_data || {};
                try {
                    sessions.set(sessionId, JSON.parse(keys.decryptionKey.decryptV1(s.ephemeral, s.mac, s.ciphertext)));
                } catch (e) { /* clé illisible : ignorée */ }
            }
            if (sessions.size) rooms.set(new M.RoomId(roomId), sessions);
        }
        if (!rooms.size) return false;
        await this.machine.importBackedUpRoomKeys(rooms, () => {}, keys.backupVersion);
        return true;
    }

    /** Vrai si ce membre a déjà un code secret (sauvegarde) sur le serveur. Une erreur (réseau,
     *  serveur) est LEVÉE, jamais prise pour « pas de code secret » : sinon l'interface proposait
     *  d'en créer un nouveau, ce qui remplaçait la sauvegarde existante. */
    async hasRecovery() {
        return JSON.parse(await this._fetch('GET', 'recovery')).exists === true;
    }

    /** Vrai si cet appareil a la clé de sauvegarde (code secret déjà saisi ou créé ici). */
    async isUnlocked() {
        return !!(await this.machine.getBackupKeys()).decryptionKey;
    }

    async _passwordKey(passphrase, salt, iterations) {
        const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveKey']);
        return crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations },
                                       base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
    }

    /** Crée la sauvegarde des clés, protégée par `passphrase` (que le serveur ne voit jamais).
     *  Si un code secret existe déjà, le serveur refuse (E2EEError 'M_RECOVERY_EXISTS') sauf
     *  demande explicite `{ replace: true }` : l'ancienne sauvegarde est alors perdue. */
    setupRecovery(passphrase, { replace = false } = {}) {
        return this._serial(async () => {
            const key = M.BackupDecryptionKey.createRandomKey();
            const publicKey = key.megolmV1PublicKey.publicKeyBase64;
            const request = { algorithm: BACKUP_ALGORITHM, auth_data: { public_key: publicKey } };
            if (replace) request.replace = true;
            const { version } = JSON.parse(await this._fetch('POST', 'room_keys/version', JSON.stringify(request)));
            const salt = crypto.getRandomValues(new Uint8Array(16));
            const iv = crypto.getRandomValues(new Uint8Array(12));
            const wrapKey = await this._passwordKey(passphrase, salt, PBKDF2_ITERATIONS);
            const ciphertext = await crypto.subtle.encrypt(
                { name: 'AES-GCM', iv, additionalData: new TextEncoder().encode(mx(this.userPk)) },
                wrapKey, new TextEncoder().encode(key.toBase64()));
            await this._fetch('PUT', 'recovery', JSON.stringify({
                v: 1, salt: b64(salt), iterations: PBKDF2_ITERATIONS, iv: b64(iv),
                ciphertext: b64(ciphertext), backup_version: version,
            }));
            await this.machine.saveBackupDecryptionKey(key, version);
            await this.machine.enableBackupV1(publicKey, version);
            await this._backup();
        });
    }

    /** Sur un nouvel appareil : retrouve la clé de sauvegarde avec le code secret, puis les clés
     *  des anciens messages. Lève E2EEError('BAD_PASSPHRASE') si le code est faux. */
    unlock(passphrase) {
        return this._serial(async () => {
            const blob = JSON.parse(await this._fetch('GET', 'recovery'));
            if (!blob.exists) throw new E2EEError('NO_RECOVERY', 'Aucun code secret enregistré.');
            const wrapKey = await this._passwordKey(passphrase, unb64(blob.salt), blob.iterations);
            let raw;
            try {
                raw = await crypto.subtle.decrypt(
                    { name: 'AES-GCM', iv: unb64(blob.iv), additionalData: new TextEncoder().encode(mx(this.userPk)) },
                    wrapKey, unb64(blob.ciphertext));
            } catch (e) {
                throw new E2EEError('BAD_PASSPHRASE', 'Code secret incorrect.');
            }
            const key = M.BackupDecryptionKey.fromBase64(new TextDecoder().decode(raw));
            const current = JSON.parse(await this._fetch('GET', 'room_keys/version'));
            if (current.auth_data.public_key !== key.megolmV1PublicKey.publicKeyBase64) {
                throw new E2EEError('BACKUP_CHANGED', 'La sauvegarde a été refaite ailleurs : code secret périmé.');
            }
            await this.machine.saveBackupDecryptionKey(key, current.version);
            await this.machine.enableBackupV1(current.auth_data.public_key, current.version);
            await this._restoreFromBackup();
            await this._backup();
        });
    }
}

export default VazimbaE2EE;
