/*
 * static/js/e2ee/chat-secret.js
 * ─────────────────────────────
 * La « conversation secrète » du chat privé : envoi chiffré des messages et des fichiers,
 * affichage déchiffré, code secret (sauvegarde des clés).
 *
 * Branché sur chat/templates/chat/room.html par quelques crochets (VZSecret.onJoin, onToggle,
 * toggle, sendMessage, appendText, appendFile, sendFile). Le moteur de chiffrement (vz-e2ee.mjs,
 * 8 Mo) n'est chargé qu'à l'ouverture d'une conversation secrète.
 *
 * Les textes viennent du dictionnaire de la page (window._CT, traduit par Django) ; le français
 * écrit ici n'est qu'un repli.
 */
(function () {
    'use strict';

    var S = window.VZSecret = { on: false };
    var enginePromise = null;
    var failed = [];                 // messages illisibles, à réessayer après le code secret
    var askedUnlock = false;
    var MAX_FILE = 25 * 1024 * 1024;

    function $(id) { return document.getElementById(id); }
    function t(key, fallback) { return (window._CT && window._CT[key]) || fallback; }
    function csrf() {
        return (document.cookie.match('(^|;)\\s*csrftoken=([^;]+)') || [])[2] || window.VZ_CSRF || '';
    }
    function icon(name) {
        var el = document.createElement('span');
        el.className = 'material-icons';
        el.setAttribute('aria-hidden', 'true');
        el.textContent = name;
        return el;
    }
    function sysMsg(text, iconName) {
        if (typeof _appendSysMsg === 'function') _appendSysMsg(text, iconName);
    }

    // ── Le moteur ──────────────────────────────────────────────────────────

    S.engine = function () {
        if (!enginePromise) {
            enginePromise = import(window.VZ_E2EE_MODULE).then(function (m) {
                S.lib = m.VazimbaE2EE;
                return m.VazimbaE2EE.open({ userPk: Number(currentUserId), csrf: csrf() });
            });
            enginePromise.catch(function (err) {
                console.error('[E2EE] moteur indisponible', err);
                enginePromise = null;
            });
        }
        return enginePromise;
    };

    // ── État de la conversation ────────────────────────────────────────────

    function banner() {
        var el = $('vz-secret-banner');
        if (el) return el;
        var log = $('id_chat_log');
        if (!log || !log.parentNode) return null;
        el = document.createElement('div');
        el.id = 'vz-secret-banner';
        el.hidden = true;
        el.appendChild(icon('lock'));
        var text = document.createElement('span');
        text.className = 'vz-secret-text';
        text.textContent = t('s_banner', 'Conversation secrète : les messages sont chiffrés de bout en bout, sur vos appareils.');
        el.appendChild(text);
        var action = document.createElement('button');
        action.type = 'button';
        action.className = 'vz-btn vz-btn--sm vz-btn--tonal vz-secret-action';
        action.hidden = true;
        el.appendChild(action);
        log.parentNode.insertBefore(el, log);
        return el;
    }

    function setState(on) {
        S.on = !!on;
        var lock = $('chat-header-lock');
        if (lock) lock.hidden = !S.on;
        var b = banner();
        if (b) b.hidden = !S.on;
        if (S.on) S.engine().then(checkRecovery).catch(function () {
            showBannerAction(t('s_unsupported', 'Ce navigateur ne permet pas les conversations secrètes.'), null);
        });
    }

    function showBannerAction(label, onClick) {
        var b = banner();
        if (!b) return;
        var action = b.querySelector('.vz-secret-action');
        if (!label) { action.hidden = true; return; }
        action.textContent = label;
        action.hidden = false;
        action.disabled = !onClick;
        action.onclick = onClick;
    }

    function changeNotice(encrypted, userId, username) {
        var me = String(userId) === String(currentUserId);
        var text;
        if (me) {
            text = encrypted
                ? t('s_you_on', 'Vous avez activé la conversation secrète : les nouveaux messages sont chiffrés de bout en bout.')
                : t('s_you_off', 'Vous avez coupé la conversation secrète : les messages suivants ne sont plus chiffrés.');
        } else {
            text = (encrypted
                ? t('s_other_on', '{name} a activé la conversation secrète : les nouveaux messages sont chiffrés de bout en bout.')
                : t('s_other_off', '{name} a coupé la conversation secrète : les messages suivants ne sont plus chiffrés.')
            ).replace('{name}', username || '');
        }
        sysMsg(text, encrypted ? 'lock' : 'lock_open');
    }

    function seen(roomKey, stamp) {
        try {
            var key = 'vz-secret-seen:' + roomKey;
            if (stamp === undefined) return localStorage.getItem(key);
            localStorage.setItem(key, String(stamp));
        } catch (e) { /* stockage indisponible */ }
        return null;
    }

    S.onJoin = function (data) {
        failed = [];
        setState(!!data.encrypted);
        // L'autre personne a changé le réglage pendant notre absence : on le dit, une fois.
        if (data.secret_at && String(data.secret_by_id) !== String(currentUserId)
                && seen(data.join) !== String(data.secret_at)) {
            var encrypted = !!data.encrypted, by = data.secret_by_id, name = data.secret_by;
            // (après le chargement des messages, pour que la ligne reste en bas de la conversation)
            setTimeout(function () { changeNotice(encrypted, by, name); }, 1200);
        }
        if (data.secret_at) seen(data.join, data.secret_at);
    };

    S.onToggle = function (data) {
        setState(!!data.encrypted);
        changeNotice(!!data.encrypted, data.user_id, data.username);
        if (typeof roomId !== 'undefined' && roomId) seen(roomId, Date.now());
    };

    // Le serveur a refusé un message (l'état avait changé entre-temps) : on se recale.
    S.resync = function (errorCode) {
        setState(errorCode === 'SECRET_ROOM');
    };

    S.toggle = function () {
        if (!roomId) return;
        var turnOn = !S.on;
        window.vzConfirm({
            title: turnOn ? t('s_ask_on_title', 'Activer la conversation secrète ?')
                          : t('s_ask_off_title', 'Couper la conversation secrète ?'),
            text: turnOn
                ? t('s_ask_on_text', 'Les nouveaux messages et fichiers seront chiffrés sur vos appareils avant de partir. Les anciens messages restent tels quels.')
                : t('s_ask_off_text', 'Les messages suivants ne seront plus chiffrés de bout en bout. Votre contact en sera prévenu.'),
            confirmText: turnOn ? t('s_activate', 'Activer') : t('s_cut', 'Couper'),
            cancelText: t('cancel', 'Annuler'),
            icon: turnOn ? 'lock' : 'lock_open',
            danger: !turnOn,
        }).then(function (answer) {
            if (!answer) return;
            var body = new FormData();
            body.append('room_id', roomId);
            body.append('on', turnOn ? '1' : '0');
            fetch(window.VZ_SECRET_URL, { method: 'POST', body: body, credentials: 'same-origin',
                                          headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' } })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d.ok) setState(d.encrypted);
                    else _showChatError(d.error || t('s_save_failed', 'Le changement n\'a pas pu être enregistré.'));
                })
                .catch(function () { _showChatError(t('s_save_failed', 'Le changement n\'a pas pu être enregistré.')); });
        });
    };

    // ── Code secret (sauvegarde des clés) ──────────────────────────────────

    function checkRecovery(engine) {
        return engine.hasRecovery().then(function (has) {
            if (!has) {
                showBannerAction(t('s_create_code', 'Créer mon code secret'), createRecovery);
                if (!askedUnlock) { askedUnlock = true; createRecovery(); }
                return;
            }
            return engine.isUnlocked().then(function (unlocked) {
                if (unlocked) { showBannerAction(null); return; }
                showBannerAction(t('s_enter_code', 'Saisir mon code secret'), unlockRecovery);
            });
        }, function (err) {
            // On ne sait pas si une sauvegarde existe (réseau, serveur) : surtout ne pas proposer
            // d'en créer une nouvelle, elle remplacerait l'ancienne. On propose de réessayer.
            console.warn('[E2EE] sauvegarde non vérifiée', err && err.code);
            showBannerAction(t('retry', 'Réessayer'), function () {
                showBannerAction(null);
                checkRecovery(engine);
            });
            _showChatError(t('s_check_failed', 'La sauvegarde de vos clés n\'a pas pu être vérifiée (connexion ?).'));
        });
    }

    function createRecovery() {
        modal({
            icon: 'key',
            title: t('s_code_title', 'Votre code secret'),
            text: t('s_code_text', 'Il protège la sauvegarde de vos clés. Avec lui, vous retrouverez vos messages secrets ' +
                  'sur un nouveau téléphone ou un autre navigateur. Vazimba ne le connaît pas et ne peut pas ' +
                  'le retrouver : notez-le en lieu sûr. (8 caractères au moins.)'),
            fields: [t('s_code', 'Code secret'), t('s_code_again', 'Le même, encore une fois')],
            ok: t('save', 'Enregistrer'), cancel: t('later', 'Plus tard'),
            check: function (v) {
                if (v[0].length < 8) return t('s_min8', 'Au moins 8 caractères.');
                if (v[0] !== v[1]) return t('s_mismatch', 'Les deux codes ne sont pas les mêmes.');
                return null;
            },
        }).then(function (v) {
            if (!v) return;
            S.engine().then(function (e) { return e.setupRecovery(v[0]); }).then(function () {
                showBannerAction(null);
                sysMsg(t('s_code_saved', 'Code secret enregistré : vos clés sont sauvegardées.'), 'key');
            }).catch(function (err) {
                console.error('[E2EE]', err);
                if (err && err.code === 'M_RECOVERY_EXISTS') {
                    // (créé entre-temps sur un autre appareil : il faut le saisir, pas le refaire)
                    _showChatError(t('s_code_exists', 'Un code secret existe déjà pour ce compte : saisissez-le.'));
                    showBannerAction(t('s_enter_code', 'Saisir mon code secret'), unlockRecovery);
                    return;
                }
                _showChatError(t('s_code_failed', 'Le code secret n\'a pas pu être enregistré. Réessayez.'));
            });
        });
    }

    function unlockRecovery() {
        modal({
            icon: 'key',
            title: t('s_enter_code', 'Saisir mon code secret'),
            text: t('s_unlock_text', 'Pour lire sur cet appareil les messages secrets envoyés avant.'),
            fields: [t('s_code', 'Code secret')], ok: t('s_unlock', 'Déverrouiller'), cancel: t('later', 'Plus tard'),
            work: function (v) {
                return S.engine().then(function (e) { return e.unlock(v[0]); }).then(function () { return null; },
                    function (err) {
                        return err && err.code === 'BAD_PASSPHRASE' ? t('s_bad_code', 'Code secret incorrect.')
                             : t('s_backup_unavailable', 'Impossible de retrouver la sauvegarde. Réessayez plus tard.');
                    });
            },
        }).then(function (v) {
            if (!v) return;
            showBannerAction(null);
            retryFailed();
        });
    }

    // ── Envoi ──────────────────────────────────────────────────────────────

    function socketOpen() {
        return chatSocket && chatSocket.readyState === WebSocket.OPEN;
    }

    function kindOf(type) {
        type = type || '';
        if (type.indexOf('image/') === 0) return 'image';
        if (type.indexOf('video/') === 0) return 'video';
        if (type.indexOf('audio/') === 0) return 'voice';
        return 'document';
    }

    S.sendMessage = function () {
        var input = $('id_chat_message_input');
        var text = input ? input.value.trim() : '';
        var file = window._selectedFile;
        if (!text && !file) return;
        if (!socketOpen()) { _showChatError(t('conn_lost', 'Connexion perdue. Reconnexion…')); return; }
        var replyId = _replyToId;
        var reply = _replyToId ? { username: _replyToUsername, body: String(_replyToContent || '').slice(0, 100) } : null;
        if (input) { input.value = ''; input.style.height = 'auto'; input.dispatchEvent(new Event('input')); }
        cancelReply();
        if (file) {
            clearFileSelection();
            S.sendFile(file, file.name, file.type, kindOf(file.type));
        }
        if (!text) return;
        var room = roomId;
        S.engine().then(function (e) {
            var content = { msgtype: 'm.text', body: text };
            if (reply) content.vz_reply = reply;
            return e.encrypt(Number(room), Number(currentFriendId), content);
        }).then(function (ciphertext) {
            var payload = { command: 'send', room: room, message: ciphertext, encrypted: true };
            if (replyId) payload.reply_to_id = replyId;
            chatSocket.send(JSON.stringify(payload));
        }).catch(function (err) {
            console.error('[E2EE] chiffrement', err);
            if (input && !input.value) {                       // (rien n'est perdu)
                input.value = text;
                input.dispatchEvent(new Event('input'));
            }
            _showChatError(t('s_enc_failed', 'Le message n\'a pas pu être chiffré : il n\'est pas parti.'));
        });
    };

    S.sendFile = function (blob, name, mime, kind) {
        if (!roomId) return;
        if (blob.size > MAX_FILE) { _showChatError(t('s_file_too_big', 'Fichier trop volumineux (25 Mo au plus).')); return; }
        var room = roomId;
        var bar = $('chat-upload-bar'), prog = $('chat-upload-progress'), pct = $('upload-progress-pct');
        if (bar && prog) { bar.style.width = '0'; prog.style.display = 'flex'; }
        Promise.all([S.engine(), blob.arrayBuffer()]).then(function (r) {
            var engine = r[0];
            var encrypted = S.lib.encryptFile(new Uint8Array(r[1]));
            var content = { msgtype: 'm.file', name: name || 'fichier', mimetype: mime || 'application/octet-stream',
                            size: blob.size, file_type: kind, file: encrypted.info };
            return engine.encrypt(Number(room), Number(currentFriendId), content).then(function (ciphertext) {
                return { ciphertext: ciphertext, data: encrypted.data };
            });
        }).then(function (p) {
            var form = new FormData();
            form.append('room_id', room);
            form.append('encrypted', '1');
            form.append('content', p.ciphertext);
            form.append('file_type', kind);
            form.append('file', new Blob([p.data], { type: 'application/octet-stream' }), 'chiffre.bin');
            var xhr = new XMLHttpRequest();
            xhr.open('POST', window.VZ_UPLOAD_URL, true);
            xhr.setRequestHeader('X-CSRFToken', csrf());
            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable && bar) {
                    var v = Math.round(e.loaded / e.total * 100);
                    bar.style.width = v + '%';
                    if (pct) pct.textContent = v + '%';
                }
            };
            xhr.onload = function () {
                if (prog) prog.style.display = 'none';
                var d = {};
                try { d = JSON.parse(xhr.responseText); } catch (e) { /* */ }
                if (xhr.status !== 200 || !d.ok) _showChatError(d.error || t('s_file_failed', 'L\'envoi du fichier a échoué.'));
            };
            xhr.onerror = function () {
                if (prog) prog.style.display = 'none';
                _showChatError(t('s_file_failed', 'L\'envoi du fichier a échoué.'));
            };
            xhr.send(form);
        }).catch(function (err) {
            console.error('[E2EE] fichier', err);
            if (prog) prog.style.display = 'none';
            _showChatError(t('s_file_enc_failed', 'Le fichier n\'a pas pu être chiffré : il n\'est pas parti.'));
        });
    };

    // ── Affichage ──────────────────────────────────────────────────────────

    function rowOf(msgId) {
        return document.querySelector('#id_chat_log [data-msg-id="' + String(msgId) + '"]');
    }

    function decrypt(data, ciphertext, room) {
        return S.engine().then(function (e) {
            return e.decrypt(Number(room), { id: data.msg_id, senderPk: Number(data.user_id),
                                             ts: Number(data.ts), ciphertext: ciphertext });
        }).then(function (r) { return r.content; });
    }

    function markLocked(row) {
        var footer = row && row.querySelector('.bubble-footer');
        if (footer && !footer.querySelector('.bubble-lock')) {
            var lock = icon('lock');
            lock.classList.add('bubble-lock');
            lock.removeAttribute('aria-hidden');
            lock.setAttribute('role', 'img');
            lock.title = t('s_e2e', 'Chiffré de bout en bout');
            lock.setAttribute('aria-label', lock.title);
            footer.insertBefore(lock, footer.firstChild);
        }
    }

    function unreadable(target, data, isFile, room) {
        target.textContent = isFile ? t('s_file_unreadable', 'Fichier illisible sur cet appareil')
                                    : t('s_unreadable', 'Message illisible sur cet appareil');
        target.classList.add('e2ee-unreadable');
        failed.push({ data: data, isFile: isFile, room: room });
        if (enginePromise) enginePromise.then(checkRecovery).catch(function () {});
    }

    S.appendText = function (data, maintainPosition, isNewMessage) {
        var copy = Object.assign({}, data);
        if (copy.reply_to_id) copy.reply_to_content = copy.reply_to_content || t('enc_msg', 'Message chiffré');
        createChatMessageElement(t('s_decrypting', 'Déchiffrement…') + '\n', data.msg_id, data.username + ': ',
                                 data.profile_image, data.user_id, data.natural_timestamp,
                                 maintainPosition, isNewMessage, copy);
        var input = $('id_chat_message_input');
        if (input && isNewMessage) input.focus();
        fillText(data, isNewMessage, roomId);
    };

    function fillText(data, isNewMessage, room) {
        var row = rowOf(data.msg_id);
        if (!row) return;
        markLocked(row);
        var target = row.querySelector('.msg-text');
        target.classList.add('e2ee-pending');
        // (la conversation au moment de l'affichage : on peut en avoir changé avant la fin du déchiffrement)
        decrypt(data, data.message, room).then(function (content) {
            var body = String((content && content.body) || '');
            target.classList.remove('e2ee-pending', 'e2ee-unreadable');
            try { target.innerHTML = validateText(body + '\n'); } catch (e) { target.textContent = body; }
            row.setAttribute('data-text', body.slice(0, 100));
            var quote = row.querySelector('.msg-quote-body');
            if (quote && content.vz_reply && content.vz_reply.body) quote.textContent = content.vz_reply.body;
        }).catch(function (err) {
            console.warn('[E2EE] message', data.msg_id, err && err.code);
            target.classList.remove('e2ee-pending');
            unreadable(target, data, false, room);
        });
    }

    // Un fichier reçu s'affiche avec le type annoncé par l'expéditeur DANS le message chiffré : on
    // n'accepte que des types sans danger (jamais de page HTML ni de SVG, qui s'exécuteraient
    // ici, sur vazimba.io, s'ils étaient ouverts dans un onglet).
    var SAFE_TYPES = /^(image\/(jpeg|png|gif|webp|bmp|heic|heif)|video\/(mp4|webm|ogg|quicktime)|audio\/[a-z0-9.+-]+|application\/pdf)(;|$)/i;
    function safeType(mime) {
        mime = String(mime || '').trim();
        return SAFE_TYPES.test(mime) ? mime : 'application/octet-stream';
    }
    function safeKind(kind, mime) {
        var real = kindOf(mime);
        // (« image », « video » ou « voice » seulement si le type du contenu le confirme)
        return (kind === real && kind !== 'document') ? kind : 'document';
    }

    S.appendFile = function (data, maintainPosition, isNewMessage) {
        var waiting = Object.assign({}, data, { _decrypted: true, file_type: 'document',
                                                file_name: t('enc_file', 'Fichier chiffré'), file_url: '#' });
        var row = appendFileMessage(waiting, maintainPosition, isNewMessage);
        if (row) row.classList.add('e2ee-file', 'e2ee-file-waiting');
        fillFile(data, row, isNewMessage, roomId);
    };

    function fillFile(data, row, isNewMessage, room) {
        var ciphertext = data.content || data.message;
        decrypt(data, ciphertext, room).then(function (content) {
            var mime = safeType(content.mimetype);
            var kind = safeKind(content.file_type, mime);
            var name = content.name || t('file', 'fichier');
            // Images et vocaux : affichés tout de suite. Vidéos et documents : seulement quand on
            // les demande (un historique plein de vidéos de 25 Mo ne se télécharge plus tout seul).
            if (kind === 'image' || kind === 'voice') { download(data, row, content, mime, kind, name, isNewMessage); return; }
            var link = row && row.querySelector('.msg-file-doc');
            if (!link) return;
            var nameEl = link.querySelector('.file-name'), hint = link.querySelector('.file-dl');
            if (nameEl) nameEl.textContent = name;
            if (hint) hint.textContent = t('s_tap_decrypt', 'Toucher pour télécharger et déchiffrer');
            link.removeAttribute('download');
            link.removeAttribute('target');
            link.setAttribute('role', 'button');
            link.onclick = function (e) {
                e.preventDefault();
                if (link.getAttribute('aria-busy') === 'true') return;
                link.setAttribute('aria-busy', 'true');
                if (hint) hint.textContent = t('s_decrypting', 'Déchiffrement…');
                download(data, row, content, mime, kind, name, false, true);
            };
        }).catch(function (err) {
            console.warn('[E2EE] fichier', data.msg_id, err && (err.code || err.message));
            var name = row && row.querySelector('.file-name');
            if (name) unreadable(name, data, true, room);
        });
    }

    function download(data, row, content, mime, kind, name, isNewMessage, openAfter) {
        fetch(data.file_url, { credentials: 'same-origin' }).then(function (r) {
            if (!r.ok) throw new Error('fichier ' + r.status);
            return r.arrayBuffer();
        }).then(function (buf) {
            var bytes = S.lib.decryptFile(new Uint8Array(buf), content.file);
            var url = URL.createObjectURL(new Blob([bytes], { type: mime }));
            var shown = Object.assign({}, data, { _decrypted: true, file_type: kind, file_name: name, file_url: url });
            var newRow = appendFileMessage(shown, true, isNewMessage, row);
            if (!newRow) return;
            newRow.classList.add('e2ee-file');
            // (un document demandé : on lance son enregistrement, comme un lien de téléchargement)
            var link = openAfter && kind === 'document' ? newRow.querySelector('.msg-file-doc') : null;
            if (link) link.click();
        }).catch(function (err) {
            console.warn('[E2EE] fichier', data.msg_id, err && (err.code || err.message));
            var nameEl = row && row.querySelector('.file-name');
            var link = row && row.querySelector('.msg-file-doc');
            if (link) link.removeAttribute('aria-busy');
            if (nameEl) nameEl.textContent = t('s_file_unreadable', 'Fichier illisible sur cet appareil');
        });
    }

    function retryFailed() {
        var again = failed;
        failed = [];
        again.forEach(function (f) {
            if (f.isFile) {
                var row = rowOf(f.data.msg_id);
                if (row) fillFile(f.data, row, false, f.room);
            } else {
                fillText(f.data, false, f.room);
            }
        });
    }

    // ── Fenêtre du code secret (feuille partagée .vz-overlay / .vz-dialog) ─

    function modal(opts) {
        return new Promise(function (resolve) {
            var overlay = document.createElement('div');
            overlay.className = 'vz-overlay';
            var card = document.createElement('form');
            card.className = 'vz-dialog vz-secret-dialog';
            card.setAttribute('role', 'dialog');
            card.setAttribute('aria-modal', 'true');
            card.noValidate = true;
            var handle = document.createElement('div');
            handle.className = 'vz-dialog-handle';
            card.appendChild(handle);
            var head = document.createElement('div');
            head.className = 'vz-dialog-head';
            head.appendChild(icon(opts.icon || 'lock'));
            var h = document.createElement('h3');
            h.className = 'vz-dialog-title';
            h.id = 'vz-secret-title-' + Date.now();
            h.textContent = opts.title;
            card.setAttribute('aria-labelledby', h.id);
            head.appendChild(h);
            card.appendChild(head);
            var p = document.createElement('p');
            p.className = 'vz-dialog-text';
            p.textContent = opts.text;
            card.appendChild(p);
            var inputs = (opts.fields || []).map(function (label, index) {
                var field = document.createElement('div');
                field.className = 'vz-field';
                var caption = document.createElement('label');
                caption.textContent = label;
                var input = document.createElement('input');
                input.type = 'password';
                input.id = h.id + '-' + index;
                input.autocomplete = opts.work ? 'current-password' : 'new-password';
                caption.htmlFor = input.id;
                field.appendChild(caption);
                field.appendChild(input);
                card.appendChild(field);
                return input;
            });
            var error = document.createElement('div');
            error.className = 'vz-field-error vz-secret-error';
            error.setAttribute('role', 'alert');
            card.appendChild(error);
            var buttons = document.createElement('div');
            buttons.className = 'vz-dialog-actions';
            var cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'vz-btn vz-btn--secondary';
            cancel.textContent = opts.cancel || t('cancel', 'Annuler');
            var ok = document.createElement('button');
            ok.type = 'submit';
            ok.className = 'vz-btn vz-btn--primary';
            ok.textContent = opts.ok || 'OK';
            buttons.appendChild(cancel);
            buttons.appendChild(ok);
            card.appendChild(buttons);
            overlay.appendChild(card);

            var done = false, previous = document.activeElement;
            function close(value) {
                if (done) return;
                done = true;
                if (window.vzLayers) window.vzLayers.remove(closeFromLayer);
                overlay.classList.remove('open');
                if (window.vzUnlock) window.vzUnlock();
                setTimeout(function () { overlay.remove(); }, 200);
                try { if (previous && previous.focus) previous.focus(); } catch (e) { /* */ }
                resolve(value);
            }
            function closeFromLayer() { close(null); }
            cancel.onclick = function () { close(null); };
            overlay.addEventListener('click', function (e) { if (e.target === overlay) close(null); });
            card.addEventListener('submit', function (e) {
                e.preventDefault();
                if (ok.disabled) return;
                var values = inputs.map(function (i) { return i.value; });
                var problem = opts.check ? opts.check(values) : null;
                if (problem) { error.textContent = problem; return; }
                if (!opts.work) { close(inputs.length ? values : true); return; }
                ok.disabled = true;
                error.textContent = t('wait', 'Un instant…');
                opts.work(values).then(function (problem2) {
                    ok.disabled = false;
                    if (problem2) { error.textContent = problem2; return; }
                    close(values);
                });
            });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') close(null);
            });
            document.body.appendChild(overlay);
            if (window.vzLock) window.vzLock();
            if (window.vzLayers) window.vzLayers.push(closeFromLayer);
            overlay.getBoundingClientRect();
            overlay.classList.add('open');
            setTimeout(function () { (inputs[0] || ok).focus(); }, 30);
        });
    }
})();
