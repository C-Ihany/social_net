/*
 * static/js/e2ee/chat-secret.js
 * ─────────────────────────────
 * La « conversation secrète » du chat privé : bouton cadenas, envoi chiffré des messages et des
 * fichiers, affichage déchiffré, code secret (sauvegarde des clés).
 *
 * Branché sur chat/templates/chat/room.html par quelques crochets (VZSecret.onJoin, onToggle,
 * sendMessage, appendText, appendFile, sendFile). Le moteur de chiffrement (vz-e2ee.mjs, 8 Mo)
 * n'est chargé qu'à l'ouverture d'une conversation secrète.
 */
(function () {
    'use strict';

    var S = window.VZSecret = { on: false };
    var enginePromise = null;
    var failed = [];                 // messages illisibles, à réessayer après le code secret
    var askedUnlock = false;

    function $(id) { return document.getElementById(id); }
    function csrf() {
        return (document.cookie.match('(^|;)\\s*csrftoken=([^;]+)') || [])[2] || window.VZ_CSRF || '';
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
        el.innerHTML = '<span class="material-icons" aria-hidden="true">lock</span>' +
            '<span class="vz-secret-text">Conversation secrète : chiffrée de bout en bout. ' +
            'Vazimba ne peut pas lire ces messages.</span>' +
            '<button type="button" class="vz-secret-action" style="display:none"></button>';
        log.parentNode.insertBefore(el, log);
        return el;
    }

    function setState(on) {
        S.on = !!on;
        var btn = $('btn-secret');
        if (btn) {
            btn.classList.toggle('secret-on', S.on);
            btn.title = S.on ? 'Conversation secrète (activée)' : 'Conversation secrète';
            var icon = btn.querySelector('.material-icons');
            if (icon) icon.textContent = S.on ? 'lock' : 'lock_open';
        }
        var b = banner();
        if (b) b.style.display = S.on ? 'flex' : 'none';
        if (S.on) S.engine().then(checkRecovery).catch(function () {
            showBannerAction('Ce navigateur ne permet pas les conversations secrètes.', null);
        });
    }

    function showBannerAction(label, onClick) {
        var b = banner();
        if (!b) return;
        var action = b.querySelector('.vz-secret-action');
        if (!label) { action.style.display = 'none'; return; }
        action.textContent = label;
        action.style.display = '';
        action.disabled = !onClick;
        action.onclick = onClick;
    }

    S.onJoin = function (data) {
        failed = [];
        setState(!!data.encrypted);
    };

    S.onToggle = function (data) {
        setState(!!data.encrypted);
        var me = String(data.user_id) === String(currentUserId);
        var who = me ? 'Vous avez' : (data.username + ' a');
        if (typeof _appendSysMsg === 'function') {
            _appendSysMsg(data.encrypted
                ? '🔒 ' + who + ' activé la conversation secrète : les nouveaux messages sont chiffrés de bout en bout.'
                : '⚠️ ' + who + ' coupé la conversation secrète : les messages suivants ne sont plus chiffrés.');
        }
    };

    // Le serveur a refusé un message (l'état avait changé entre-temps) : on se recale.
    S.resync = function (errorCode) {
        setState(errorCode === 'SECRET_ROOM');
    };

    S.toggle = function () {
        if (!roomId) return;
        var turnOn = !S.on;
        var text = turnOn
            ? 'Les nouveaux messages et fichiers seront chiffrés sur vos appareils : personne d\'autre, ' +
              'pas même Vazimba, ne pourra les lire. Les anciens messages restent tels quels.'
            : 'Les messages suivants ne seront PLUS chiffrés de bout en bout. Votre contact en sera prévenu.';
        modal({ title: turnOn ? 'Activer la conversation secrète ?' : 'Couper la conversation secrète ?',
                text: text, ok: turnOn ? 'Activer' : 'Couper', cancel: 'Annuler' }).then(function (answer) {
            if (!answer) return;
            var body = new FormData();
            body.append('room_id', roomId);
            body.append('on', turnOn ? '1' : '0');
            fetch(window.VZ_SECRET_URL, { method: 'POST', body: body, credentials: 'same-origin',
                                          headers: { 'X-CSRFToken': csrf() } })
                .then(function (r) { return r.json(); })
                .then(function (d) { if (d.ok) setState(d.encrypted); })
                .catch(function () { _showChatError('Le changement n\'a pas pu être enregistré.'); });
        });
    };

    // ── Code secret (sauvegarde des clés) ──────────────────────────────────

    function checkRecovery(engine) {
        return engine.hasRecovery().then(function (has) {
            if (!has) {
                showBannerAction('Créer mon code secret', createRecovery);
                if (!askedUnlock) { askedUnlock = true; createRecovery(); }
                return;
            }
            return engine.isUnlocked().then(function (unlocked) {
                if (unlocked) { showBannerAction(null); return; }
                showBannerAction('Saisir mon code secret', unlockRecovery);
            });
        });
    }

    function createRecovery() {
        modal({
            title: 'Votre code secret',
            text: 'Il protège la sauvegarde de vos clés. Avec lui, vous retrouverez vos messages secrets ' +
                  'sur un nouveau téléphone ou un autre navigateur. Vazimba ne le connaît pas et ne peut PAS ' +
                  'le retrouver : notez-le en lieu sûr. (8 caractères au moins.)',
            fields: ['Code secret', 'Le même, encore une fois'],
            ok: 'Enregistrer', cancel: 'Plus tard',
            check: function (v) {
                if (v[0].length < 8) return 'Au moins 8 caractères.';
                if (v[0] !== v[1]) return 'Les deux codes ne sont pas les mêmes.';
                return null;
            },
        }).then(function (v) {
            if (!v) return;
            S.engine().then(function (e) { return e.setupRecovery(v[0]); }).then(function () {
                showBannerAction(null);
                if (typeof _appendSysMsg === 'function') _appendSysMsg('🔑 Code secret enregistré : vos clés sont sauvegardées.');
            }).catch(function (err) {
                console.error('[E2EE]', err);
                _showChatError('Le code secret n\'a pas pu être enregistré. Réessayez.');
            });
        });
    }

    function unlockRecovery() {
        modal({
            title: 'Saisir mon code secret',
            text: 'Pour lire sur cet appareil les messages secrets envoyés avant.',
            fields: ['Code secret'], ok: 'Déverrouiller', cancel: 'Plus tard',
            work: function (v) {
                return S.engine().then(function (e) { return e.unlock(v[0]); }).then(function () { return null; },
                    function (err) {
                        return err && err.code === 'BAD_PASSPHRASE' ? 'Code secret incorrect.'
                             : 'Impossible de retrouver la sauvegarde. Réessayez plus tard.';
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
        if (!socketOpen()) { _showChatError(_CT ? _CT.conn_lost : 'Connexion perdue. Reconnexion…'); return; }
        var replyId = _replyToId;
        var reply = _replyToId ? { username: _replyToUsername, body: String(_replyToContent || '').slice(0, 100) } : null;
        if (input) { input.value = ''; input.style.height = 'auto'; }
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
            if (input && !input.value) input.value = text;     // (rien n'est perdu)
            _showChatError('Le message n\'a pas pu être chiffré : il n\'est pas parti.');
        });
    };

    S.sendFile = function (blob, name, mime, kind) {
        if (!roomId) return;
        if (blob.size > 25 * 1024 * 1024) { _showChatError('Fichier trop volumineux (max 25 Mo).'); return; }
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
                if (xhr.status !== 200 || !d.ok) _showChatError(d.error || 'Échec de l\'envoi du fichier.');
            };
            xhr.onerror = function () {
                if (prog) prog.style.display = 'none';
                _showChatError('Échec de l\'envoi du fichier.');
            };
            xhr.send(form);
        }).catch(function (err) {
            console.error('[E2EE] fichier', err);
            if (prog) prog.style.display = 'none';
            _showChatError('Le fichier n\'a pas pu être chiffré : il n\'est pas parti.');
        });
    };

    // ── Affichage ──────────────────────────────────────────────────────────

    function rowOf(msgId) {
        return document.querySelector('#id_chat_log [data-msg-id="' + String(msgId) + '"]');
    }

    function decrypt(data, ciphertext) {
        return S.engine().then(function (e) {
            return e.decrypt(Number(roomId), { id: data.msg_id, senderPk: Number(data.user_id),
                                               ts: Number(data.ts), ciphertext: ciphertext });
        }).then(function (r) { return r.content; });
    }

    function markLocked(row) {
        var footer = row && row.querySelector('.bubble-footer');
        if (footer && !footer.querySelector('.bubble-lock')) {
            var lock = document.createElement('span');
            lock.className = 'material-icons bubble-lock';
            lock.title = 'Chiffré de bout en bout';
            lock.textContent = 'lock';
            footer.insertBefore(lock, footer.firstChild);
        }
    }

    function unreadable(target, data, isFile) {
        target.textContent = isFile ? '🔒 Fichier illisible sur cet appareil' : '🔒 Message illisible sur cet appareil';
        failed.push({ data: data, isFile: isFile });
        if (enginePromise) enginePromise.then(checkRecovery).catch(function () {});
    }

    S.appendText = function (data, maintainPosition, isNewMessage) {
        var copy = Object.assign({}, data);
        if (copy.reply_to_id) copy.reply_to_content = copy.reply_to_content || '🔒 Message chiffré';
        createChatMessageElement('🔒 …\n', data.msg_id, data.username + ': ', data.profile_image, data.user_id,
                                 data.natural_timestamp, maintainPosition, isNewMessage, copy);
        var input = $('id_chat_message_input');
        if (input && isNewMessage) input.focus();
        fillText(data, isNewMessage);
    };

    function fillText(data, isNewMessage) {
        var row = rowOf(data.msg_id);
        if (!row) return;
        markLocked(row);
        var target = row.querySelector('.msg-text');
        decrypt(data, data.message).then(function (content) {
            var body = String((content && content.body) || '');
            try { target.innerHTML = validateText(body + '\n'); } catch (e) { target.textContent = body; }
            row.setAttribute('data-text', body.slice(0, 100));
            var quote = row.querySelector('.msg-quote-body');
            if (quote && content.vz_reply && content.vz_reply.body) quote.textContent = content.vz_reply.body;
            if (isNewMessage && typeof updateSidebarPreview === 'function') updateSidebarPreview(data.user_id, body);
        }).catch(function (err) {
            console.warn('[E2EE] message', data.msg_id, err && err.code);
            unreadable(target, data, false);
        });
    }

    S.appendFile = function (data, maintainPosition, isNewMessage) {
        var waiting = Object.assign({}, data, { _decrypted: true, file_type: 'document',
                                                file_name: '🔒 Fichier chiffré…', file_url: '#' });
        var row = appendFileMessage(waiting, maintainPosition, isNewMessage);
        fillFile(data, row, isNewMessage);
    };

    function fillFile(data, row, isNewMessage) {
        var ciphertext = data.content || data.message;
        var content;
        decrypt(data, ciphertext).then(function (c) {
            content = c;
            return fetch(data.file_url, { credentials: 'same-origin' });
        }).then(function (r) {
            if (!r.ok) throw new Error('fichier ' + r.status);
            return r.arrayBuffer();
        }).then(function (buf) {
            var bytes = S.lib.decryptFile(new Uint8Array(buf), content.file);
            var url = URL.createObjectURL(new Blob([bytes], { type: content.mimetype || 'application/octet-stream' }));
            var shown = Object.assign({}, data, { _decrypted: true, file_type: content.file_type || 'document',
                                                  file_name: content.name || 'fichier', file_url: url });
            var newRow = appendFileMessage(shown, true, isNewMessage, row);
            if (newRow) newRow.classList.add('e2ee-file');
        }).catch(function (err) {
            console.warn('[E2EE] fichier', data.msg_id, err && (err.code || err.message));
            var name = row && row.querySelector('.file-name');
            if (name) unreadable(name, data, true);
        });
    }

    function retryFailed() {
        var again = failed;
        failed = [];
        again.forEach(function (f) {
            if (f.isFile) {
                var row = rowOf(f.data.msg_id);
                if (row) fillFile(f.data, row, false);
            } else {
                fillText(f.data, false);
            }
        });
    }

    // ── Petite fenêtre (choix, code secret) ────────────────────────────────

    function modal(opts) {
        return new Promise(function (resolve) {
            var overlay = document.createElement('div');
            overlay.className = 'vz-secret-modal';
            var card = document.createElement('div');
            card.className = 'vz-secret-card';
            card.setAttribute('role', 'dialog');
            card.setAttribute('aria-modal', 'true');
            var h = document.createElement('h3');
            h.textContent = opts.title;
            var p = document.createElement('p');
            p.textContent = opts.text;
            card.appendChild(h);
            card.appendChild(p);
            var inputs = (opts.fields || []).map(function (label) {
                var input = document.createElement('input');
                input.type = 'password';
                input.placeholder = label;
                input.setAttribute('aria-label', label);
                input.autocomplete = 'new-password';
                card.appendChild(input);
                return input;
            });
            var error = document.createElement('div');
            error.className = 'vz-secret-error';
            card.appendChild(error);
            var buttons = document.createElement('div');
            buttons.className = 'vz-secret-buttons';
            var cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'vz-btn';
            cancel.textContent = opts.cancel || 'Annuler';
            var ok = document.createElement('button');
            ok.type = 'button';
            ok.className = 'vz-btn vz-btn--primary';
            ok.textContent = opts.ok || 'OK';
            buttons.appendChild(cancel);
            buttons.appendChild(ok);
            card.appendChild(buttons);
            overlay.appendChild(card);
            document.body.appendChild(overlay);
            (inputs[0] || ok).focus();

            function close(value) { overlay.remove(); resolve(value); }
            cancel.onclick = function () { close(null); };
            ok.onclick = function () {
                var values = inputs.map(function (i) { return i.value; });
                var problem = opts.check ? opts.check(values) : null;
                if (problem) { error.textContent = problem; return; }
                if (!opts.work) { close(inputs.length ? values : true); return; }
                ok.disabled = true;
                error.textContent = 'Un instant…';
                opts.work(values).then(function (problem2) {
                    ok.disabled = false;
                    if (problem2) { error.textContent = problem2; return; }
                    close(values);
                });
            };
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') ok.onclick();
                if (e.key === 'Escape') close(null);
            });
        });
    }
})();
