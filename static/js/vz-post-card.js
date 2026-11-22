/* ════════════════════════════════════════════════════════════════════════
   vz-post-card.js — comportements partagés de la carte de post
   (fil, profil, groupe, hashtag, pages chargées en AJAX)
   • vzPostMenu(btn)        : menu ⋯ (copier le lien, partager, sauvegarder,
                              republier, masquer, signaler, bloquer, modifier, supprimer)
   • vzPostBookmark(id,btn) : sauvegarder / retirer, avec toast et action « Voir »
   • vzPostRepost(id)       : republier / annuler
   • vzPostHide(id)         : masquer la carte avec « Annuler »
   • vzPostDelete(btn)      : supprimer (POST après confirmation)
   • compte à rebours Vintana : une seule boucle pour toutes les capsules
   • réactions, commentaires, réponses, « Voir plus », hashtags/mentions :
     une seule implémentation pour toutes les pages qui incluent
     post/_post_card_assets.html (qui fournit window.VZ_CARD)
   Dépend de vz-core.js (vzMenu, vzToast, vzShare, vzCopy, vzConfirm) et de
   window.VZ_URLS / window.VZ_CSRF / window.VZ_I18N fournis par base.html.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    var I18N = window.VZ_I18N || {};
    var URLS = window.VZ_URLS || {};
    function t(k, fb) { return I18N[k] || fb; }
    function csrf() {
        if (window.VZ_CSRF) return window.VZ_CSRF;
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }
    function post(url, data) {
        var fd = new FormData();
        Object.keys(data || {}).forEach(function (k) { fd.append(k, data[k]); });
        fd.append('csrfmiddlewaretoken', csrf());
        return fetch(url, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    }
    function card(id) { return document.getElementById('post-' + id); }
    function absolute(url) { try { return new URL(url, location.href).href; } catch (e) { return url; } }

    /* ── Sauvegarder ─────────────────────────────────────────────────── */
    window.vzPostBookmark = function (postId, btn) {
        if (!URLS.bookmark) return;
        btn = btn || document.getElementById('bk-btn-' + postId);
        return post(URLS.bookmark, { post_id: postId }).then(function (d) {
            if (!d.ok) throw new Error('ko');
            var saved = !!d.saved;
            var c = card(postId);
            if (c) {
                c.querySelectorAll('[data-bookmarked]').forEach(function (el) { el.setAttribute('data-bookmarked', saved ? '1' : '0'); });
                var b = c.querySelector('#bk-btn-' + postId);
                if (b) {
                    b.classList.toggle('bookmarked', saved);
                    b.setAttribute('aria-pressed', saved ? 'true' : 'false');
                    var ic = b.querySelector('.material-icons'); if (ic) ic.textContent = saved ? 'bookmark' : 'bookmark_border';
                    b.setAttribute('aria-label', saved ? t('postUnsave', 'Retirer des sauvegardes') : t('postSave', 'Sauvegarder'));
                }
            }
            if (saved) {
                window.vzToast(t('postSaved', 'Post sauvegardé'), { type: 'success',
                    action: URLS.bookmarks ? { label: t('view', 'Voir'), onClick: function () { location.href = URLS.bookmarks; } } : null });
            } else {
                window.vzToast(t('postUnsaved', 'Retiré des sauvegardes'), 'info');
            }
            return saved;
        }).catch(function () { window.vzToast(t('error', 'Une erreur est survenue'), 'error'); });
    };

    /* ── Republier ───────────────────────────────────────────────────── */
    window.vzPostRepost = function (postId) {
        if (!URLS.repost) return;
        return post(URLS.repost, { post_id: postId }).then(function (d) {
            var c = card(postId);
            if (c) c.querySelectorAll('[data-reposted]').forEach(function (el) { el.setAttribute('data-reposted', d.reposted ? '1' : '0'); });
            var cnt = document.getElementById('repost-count-' + postId);
            if (cnt) { cnt.textContent = d.repost_count > 0 ? d.repost_count : ''; cnt.style.display = d.repost_count > 0 ? '' : 'none'; }
            var wrap = document.getElementById('repost-count-wrap-' + postId);
            if (wrap) wrap.hidden = !(d.repost_count > 0);
            window.vzToast(d.reposted ? t('reposted', 'Republié sur votre profil') : t('unreposted', 'Republication annulée'), d.reposted ? 'success' : 'info');
        }).catch(function () { window.vzToast(t('error', 'Une erreur est survenue'), 'error'); });
    };

    /* ── Masquer ─────────────────────────────────────────────────────── */
    window.vzPostHide = function (postId) {
        if (!URLS.hide) return;
        var c = card(postId);
        if (c) { c.classList.add('pc-hiding'); setTimeout(function () { c.style.display = 'none'; }, 220); }
        return post(URLS.hide, { post_id: postId }).then(function () {
            window.vzToast(t('postHidden', 'Post masqué'), { type: 'info', duration: 6000,
                action: { label: t('undo', 'Annuler'), onClick: function () {
                    post(URLS.hide, { post_id: postId, undo: '1' }).then(function () {
                        if (c) { c.style.display = ''; c.classList.remove('pc-hiding'); }
                    });
                } } });
        }).catch(function () {
            if (c) { c.style.display = ''; c.classList.remove('pc-hiding'); }
            window.vzToast(t('error', 'Une erreur est survenue'), 'error');
        });
    };

    /* ── Supprimer (une seule confirmation, puis POST) ───────────────── */
    window.vzPostDelete = function (btn) {
        var d = btn.dataset, c = card(d.postId);
        if (!d.deleteNowUrl) { location.href = d.deleteUrl; return; }
        return post(d.deleteNowUrl, {}).then(function () {
            var cfg = window.VZ_CARD || {};
            if (cfg.detail || !c) { location.href = cfg.afterDelete || '/'; return; }
            c.classList.add('pc-hiding');
            setTimeout(function () { c.remove(); }, 220);
            window.vzToast(t('postDeleted', 'Post supprimé'), 'info');
        }).catch(function () { location.href = d.deleteUrl; });
    };

    /* ── Menu ⋯ ───────────────────────────────────────────────────────── */
    window.vzPostMenu = function (btn) {
        var d = btn.dataset;
        var id = d.postId, url = absolute(d.postUrl), owner = d.owner === '1';
        var saved = d.bookmarked === '1', reposted = d.reposted === '1';
        var items = [
            { icon: 'link', label: t('copyLink', 'Copier le lien'), onClick: function () { window.vzCopy(url); } },
            { icon: 'share', label: t('share', 'Partager'), onClick: function () { window.vzShare({ title: d.postTitle || document.title, url: url }); } },
            { icon: saved ? 'bookmark' : 'bookmark_border', label: saved ? t('postUnsave', 'Retirer des sauvegardes') : t('postSave', 'Sauvegarder'),
              onClick: function () { window.vzPostBookmark(id); } },
            URLS.repost ? { icon: 'repeat', label: reposted ? t('unrepost', 'Annuler la republication') : t('repost', 'Republier'),
              onClick: function () { window.vzPostRepost(id); } } : null,
            'sep'
        ];
        if (d.pinUrl && typeof window.vzPostPin === 'function') {
            items.push({ icon: 'push_pin', label: d.pinLabel || 'Épingler', onClick: function () { window.vzPostPin(d.pinUrl); } });
        }
        if (owner) {
            items.push({ icon: 'edit', label: t('edit', 'Modifier'), href: d.editUrl });
            items.push({ icon: 'delete_outline', label: t('delete', 'Supprimer'), danger: true, onClick: function () {
                window.vzConfirm({ text: t('deleteConfirm', 'Supprimer ce post ?'), danger: true, confirmText: t('delete', 'Supprimer') })
                    .then(function (yes) { if (yes) window.vzPostDelete(btn); });
            } });
        } else {
            items.push({ icon: 'visibility_off', label: t('postHide', 'Masquer ce post'), onClick: function () { window.vzPostHide(id); } });
            items.push({ icon: 'flag', label: t('report', 'Signaler'), onClick: function () {
                if (window.openReportModal) window.openReportModal('post', id);
            } });
            if (d.blockUrl) items.push({ icon: 'block', label: t('block', 'Bloquer') + ' ' + (d.authorName || ''), danger: true, onClick: function () {
                window.vzConfirm({ text: t('blockConfirm', 'Bloquer cette personne ? Vous ne verrez plus ses publications.'), danger: true, confirmText: t('block', 'Bloquer') })
                    .then(function (yes) {
                        if (!yes) return;
                        post(d.blockUrl, {}).then(function () { location.reload(); })
                            .catch(function () { location.href = d.blockUrl; });
                    });
            } });
        }
        window.vzMenu(btn, items, { title: d.authorName ? '@' + d.authorName : '' });
    };

    /* ── Compte à rebours Vintana : une seule boucle ─────────────────── */
    function tickVintana() {
        var nodes = document.querySelectorAll('.vt-cntdwn[data-target]');
        if (!nodes.length) return;
        var now = Date.now();
        for (var i = 0; i < nodes.length; i++) {
            var target = Date.parse(nodes[i].getAttribute('data-target'));
            if (isNaN(target)) continue;
            var diff = target - now;
            if (diff <= 0) { nodes[i].textContent = t('now', 'maintenant !'); continue; }
            var dd = Math.floor(diff / 86400000), h = Math.floor(diff % 86400000 / 3600000),
                m = Math.floor(diff % 3600000 / 60000), s = Math.floor(diff % 60000 / 1000);
            nodes[i].textContent = (dd > 0 ? dd + 'j ' : '') + (h > 0 ? h + 'h ' : '') + (m > 0 ? m + 'min ' : '') + s + 's';
        }
    }
    setInterval(tickVintana, 1000);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', tickVintana); else tickVintana();
})();

/* ════════════════════════════════════════════════════════════════════════
   Carte de post : réactions, commentaires, réponses, « Voir plus »,
   hashtags et mentions. Actif uniquement quand la page inclut
   post/_post_card_assets.html (window.VZ_CARD) ; les pages qui portent
   encore leur propre copie de ces fonctions ne sont pas touchées.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    var CFG = window.VZ_CARD;
    if (!CFG) { legacyCompat(); return; }
    /* Pages qui affichent la carte sans post/_post_card_assets.html (elles
       portent encore leur propre copie des fonctions) : la carte n'a plus de
       onclick sur le texte ni de style="display:none", on rétablit donc ce que
       ces copies attendent. À retirer quand toutes les pages incluent le partiel. */
    function legacyCompat() {
        function unhide() {
            document.querySelectorAll('.post-card [hidden]').forEach(function (el) {
                if (el.matches('.pc-reaction-bar, .pc-footer-count, .pc-comment-replies, .pc-repost-count')) {
                    el.hidden = false; el.style.display = 'none';
                }
            });
        }
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('.pc-read-more');
            if (btn && typeof window.expandBodyBtn === 'function') { window.expandBodyBtn(btn); return; }
            var body = e.target.closest('.pc-body');
            if (body && !e.target.closest('a, button, video, img') && typeof window.expandBody === 'function') window.expandBody(body);
        });
        function start() {
            unhide();
            try { new MutationObserver(unhide).observe(document.body, { childList: true, subtree: true }); } catch (e) {}
        }
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
    }
    var U = CFG.urls || {}, T = CFG.i18n || {};
    var EMOJIS = { like: '👍', heart: '❤️', laugh: '😂', wow: '😮', sad: '😢' };
    var LABELS = { like: T.like, heart: T.love, laugh: T.haha, wow: T.wow, sad: T.sad };
    var ME = CFG.userId || 0;

    function $(id) { return document.getElementById(id); }
    function csrf() {
        if (window.VZ_CSRF) return window.VZ_CSRF;
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }
    function send(url, data) {
        var fd = new FormData();
        Object.keys(data || {}).forEach(function (k) { fd.append(k, data[k]); });
        fd.append('csrfmiddlewaretoken', csrf());
        return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
    }
    function esc(str) {
        return String(str == null ? '' : str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function withId(tpl, id) { return String(tpl || '').replace('/0/', '/' + id + '/'); }
    function fail() { if (window.vzToast) window.vzToast((window.VZ_I18N || {}).error || 'Une erreur est survenue', 'error'); }
    window.escHtml = esc;
    window.commentDeleteUrl = function (id) { return withId(U.delComment, id); };

    /* ── Sélecteur de réactions ──────────────────────────────────────── */
    var pickerTimers = {}, userReactions = {};

    /* Le sélecteur est en position:fixed ; si un ancêtre est transformé,
       l'origine n'est plus le viewport : on mesure l'origine réelle et on
       compense. */
    function positionPicker(picker, anchor) {
        if (!picker || !anchor) return;
        var rect = anchor.getBoundingClientRect();
        picker.style.visibility = 'hidden';
        picker.style.display = 'flex';
        picker.style.transform = 'none';
        picker.style.bottom = 'auto';
        picker.style.right = 'auto';
        picker.style.left = '0px';
        picker.style.top = '0px';
        var ph = picker.offsetHeight || 56, pw = picker.offsetWidth || 200;
        var origin = picker.getBoundingClientRect();
        picker.style.display = '';
        picker.style.visibility = '';
        var top = rect.top - ph - 10;
        if (top < 8) top = rect.bottom + 8;
        var left = rect.left + rect.width / 2 - pw / 2;
        if (left < 8) left = 8;
        if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
        picker.style.top = (top - origin.top) + 'px';
        picker.style.left = (left - origin.left) + 'px';
    }
    function showPicker(postId) {
        var p = $('picker-' + postId);
        if (!p) return;
        positionPicker(p, $('react-btn-' + postId) || $('reaction-wrap-' + postId));
        p.classList.add('open');
    }
    window.openPicker = function (postId) {
        clearTimeout(pickerTimers[postId]);
        pickerTimers[postId] = setTimeout(function () { showPicker(postId); }, 200);
    };
    window.closePicker = function (postId) {
        clearTimeout(pickerTimers[postId]);
        pickerTimers[postId] = setTimeout(function () {
            var p = $('picker-' + postId);
            if (p) p.classList.remove('open');
        }, 150);
    };
    function closeAllPickers() {
        document.querySelectorAll('.reaction-picker.open').forEach(function (p) { p.classList.remove('open'); });
    }
    document.addEventListener('click', function (e) {
        if (!e.target.closest('.reaction-wrap')) closeAllPickers();
    });

    /* Appui long sur mobile — délégué, donc valable aussi pour les cartes
       chargées plus tard (défilement infini, nouveau post). */
    if ('ontouchstart' in window) {
        var lpTimer = null, lpWrap = null;
        var wrapOf = function (e) { return e.target.closest ? e.target.closest('.reaction-wrap') : null; };
        document.addEventListener('touchstart', function (e) {
            var wrap = wrapOf(e);
            if (!wrap) { if (!e.target.closest('.reaction-picker')) closeAllPickers(); return; }
            if (e.target.closest('.reaction-picker')) return;
            var postId = wrap.id.replace('reaction-wrap-', '');
            lpWrap = wrap;
            clearTimeout(lpTimer);
            lpTimer = setTimeout(function () {
                lpTimer = null;
                clearTimeout(pickerTimers[postId]);
                showPicker(postId);
                wrap._longPressed = true;      // bloque le clic « réaction rapide » qui suit
            }, 450);
        }, { passive: true });
        document.addEventListener('touchmove', function () { if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; } }, { passive: true });
        document.addEventListener('touchend', function (e) {
            if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
            if (lpWrap && lpWrap._longPressed) { e.preventDefault(); lpWrap._longPressed = false; }
            lpWrap = null;
        }, { passive: false });
        document.addEventListener('contextmenu', function (e) { if (wrapOf(e)) e.preventDefault(); });
    }

    window.quickReact = function (postId) {
        var btn = $('react-btn-' + postId);
        var cur = userReactions[postId] !== undefined ? userReactions[postId]
                : (btn && btn.dataset.reaction) || (btn && btn.classList.contains('liked') ? 'like' : null);
        window.sendReaction(postId, cur || 'like');   // même réaction renvoyée = retrait
    };
    window.sendReaction = function (postId, reactionType) {
        window.closePicker(postId);
        return send(U.react, { post_id: postId, reaction: reactionType || 'like' }).then(function (data) {
            var mine = data.user_reaction || null;
            userReactions[postId] = mine;
            var btn = $('react-btn-' + postId), icon = $('react-icon-' + postId), label = $('react-label-' + postId);
            if (btn) { btn.classList.toggle('liked', !!mine); btn.dataset.reaction = mine || ''; }
            if (icon) {
                if (mine && EMOJIS[mine]) icon.textContent = EMOJIS[mine];
                else icon.innerHTML = '<span class="material-icons">thumb_up_off_alt</span>';
            }
            if (label) label.textContent = (mine && LABELS[mine]) || LABELS.like || '';
            var picker = $('picker-' + postId);
            if (picker) picker.querySelectorAll('.reaction-emoji-btn').forEach(function (b) {
                b.classList.toggle('selected', !!mine && b.dataset.reaction === mine);
            });
            var bar = $('reaction-bar-' + postId), summary = $('reaction-summary-' + postId), total = $('reaction-total-' + postId);
            if (total) total.textContent = data.total;
            if (bar) bar.hidden = !(data.total > 0);
            if (summary) {
                var html = '';
                Object.keys(data.counts || {}).forEach(function (rt) {
                    if (EMOJIS[rt]) html += '<span class="rc-emoji" data-type="' + rt + '">' + EMOJIS[rt] + '</span>';
                });
                summary.innerHTML = html;
            }
        }).catch(fail);
    };

    /* ── Panneau de commentaires ─────────────────────────────────────── */
    function subscribe(postId, on) {
        if (window.notificationSocketSend) {
            window.notificationSocketSend({ command: on ? 'subscribe_post' : 'unsubscribe_post', post_id: postId });
        }
    }
    window.toggleComments = function (postId) {
        var panel = $('comment-panel-' + postId), btn = $('comment-btn-' + postId);
        if (!panel) return;
        var ta = $('comment-input-' + postId);
        if (panel.classList.contains('pc-comment-panel--static')) { if (ta) ta.focus(); return; }
        var open = !panel.classList.contains('open');
        panel.classList.toggle('open', open);
        if (btn) { btn.classList.toggle('active', open); btn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
        subscribe(postId, open);
        if (!open || !ta) return;
        /* Focus synchrone (iOS bloque focus() dans un setTimeout) */
        void panel.offsetHeight;
        ta.focus();
        requestAnimationFrame(function () {
            var rect = ta.getBoundingClientRect();
            if (rect.bottom > window.innerHeight - 76 || rect.top < 64) ta.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
    };
    window.autoResize = function (el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    };
    window.updateCommentCount = function (postId) {
        var list = $('comment-list-' + postId);
        var cnt = list ? list.querySelectorAll('.pc-comment-item, .pc-comment-reply-item').length : 0;
        var badge = $('comment-count-' + postId);
        if (badge) { badge.textContent = cnt > 0 ? '(' + cnt + ')' : ''; badge.hidden = !(cnt > 0); }
    };

    function profileUrl(id) { return withId(U.profile, id); }
    function commentHtml(c, postId, isReply) {
        var addUrl = withId(U.addComment, postId);
        var canDelete = c.can_delete !== undefined ? c.can_delete
            : !!(ME && (c.author_id === ME || c.post_author_id === ME));
        var tools = '';
        if (!isReply) {
            tools += '<button class="pc-comment-reply-btn vz-tap" type="button" onclick="toggleReplyForm(' + c.id + ',' + postId + ',\'' + addUrl + '\')">' + esc(T.reply) + '</button>';
        }
        tools += canDelete
            ? '<button class="pc-comment-del vz-tap" type="button" onclick="deleteComment(' + c.id + ', commentDeleteUrl(' + c.id + '))">' + esc(T.del) + '</button>'
            : '<button class="pc-comment-del vz-tap" type="button" onclick="openReportModal(\'comment\',\'' + c.id + '\')">' + esc(T.report) + '</button>';
        var html = '<div class="' + (isReply ? 'pc-comment-reply-item' : 'pc-comment-item') + '" id="comment-item-' + c.id + '">'
            + '<a href="' + profileUrl(c.author_id) + '"><img class="' + (isReply ? 'reply-avatar' : 'cmt-avatar') + '" src="' + esc(c.avatar) + '" alt="' + esc(c.author) + '"></a>'
            + '<div class="pc-comment-right">'
            +   '<div class="pc-comment-bubble">'
            +     '<a class="pc-comment-author" href="' + profileUrl(c.author_id) + '">' + esc(c.author) + '</a>'
            +     '<p class="pc-comment-body">' + esc(c.body) + '</p>'
            +   '</div>'
            +   '<div class="pc-comment-footer"><span class="pc-comment-time">' + esc(c.created_at) + '</span>' + tools + '</div>';
        if (!isReply) {
            html += '<div class="pc-comment-replies" id="replies-' + c.id + '" hidden></div>'
                + '<div class="pc-reply-form-wrap" id="reply-form-' + c.id + '">'
                +   '<div class="pc-reply-input-wrap">'
                +     '<textarea class="pc-reply-textarea" id="reply-input-' + c.id + '" rows="1" maxlength="1000" placeholder="' + esc(T.replyPh) + '"'
                +     ' onkeydown="handleReplyKey(event,' + c.id + ',' + postId + ',\'' + addUrl + '\')" oninput="autoResize(this)"></textarea>'
                +   '</div>'
                +   '<button class="pc-comment-send" type="button" aria-label="' + esc(T.reply) + '" onclick="submitReply(' + c.id + ',' + postId + ',\'' + addUrl + '\')">'
                +     '<span class="material-icons" aria-hidden="true">send</span></button>'
                + '</div>';
        }
        return html + '</div></div>';
    }
    function appendComment(c, postId) {
        if ($('comment-item-' + c.id)) return;            // déjà affiché (le nôtre, par exemple)
        if (c.parent_id) {
            var replies = $('replies-' + c.parent_id);
            if (!replies) return;
            replies.hidden = false; replies.style.display = '';
            replies.insertAdjacentHTML('beforeend', commentHtml(c, postId, true));
        } else {
            var list = $('comment-list-' + postId);
            if (!list) return;
            list.insertAdjacentHTML('beforeend', commentHtml(c, postId, false));
            list.scrollTop = list.scrollHeight;
        }
        lastId[postId] = Math.max(lastId[postId] || 0, c.id);
        window.updateCommentCount(postId);
    }
    function flashError(ta) {
        if (!ta) return;
        ta.classList.add('is-invalid');
        setTimeout(function () { ta.classList.remove('is-invalid'); }, 2000);
        fail();
    }

    window.handleCommentKey = function (evt, postId, url) {
        if (evt.key === 'Enter' && !evt.shiftKey) { evt.preventDefault(); window.submitComment(postId, url); }
    };
    window.submitComment = function (postId, url) {
        var ta = $('comment-input-' + postId), btn = $('comment-send-' + postId);
        if (!ta) return;
        var body = ta.value.trim();
        if (!body) return;
        if (btn) btn.disabled = true;
        send(url || withId(U.addComment, postId), { body: body }).then(function (data) {
            if (btn) btn.disabled = false;
            if (!data.ok) { flashError(ta); return; }
            ta.value = ''; ta.style.height = 'auto';
            appendComment(data, postId);
        }).catch(function () { if (btn) btn.disabled = false; flashError(ta); });
    };

    window.toggleReplyForm = function (commentId) {
        var form = $('reply-form-' + commentId);
        if (!form) return;
        var open = !form.classList.contains('open');
        document.querySelectorAll('.pc-reply-form-wrap.open').forEach(function (el) { el.classList.remove('open'); });
        form.classList.toggle('open', open);
        if (open) { var ta = $('reply-input-' + commentId); if (ta) ta.focus(); }
    };
    window.handleReplyKey = function (evt, parentId, postId, url) {
        if (evt.key === 'Enter' && !evt.shiftKey) { evt.preventDefault(); window.submitReply(parentId, postId, url); }
    };
    window.submitReply = function (parentId, postId, url) {
        var ta = $('reply-input-' + parentId);
        if (!ta) return;
        var body = ta.value.trim();
        if (!body) return;
        send(url || withId(U.addComment, postId), { body: body, parent_id: parentId }).then(function (data) {
            if (!data.ok) { flashError(ta); return; }
            ta.value = ''; ta.style.height = 'auto';
            var form = $('reply-form-' + parentId);
            if (form) form.classList.remove('open');
            if (!data.parent_id) data.parent_id = parentId;
            appendComment(data, postId);
        }).catch(function () { flashError(ta); });
    };

    window.deleteComment = function (commentId, url) {
        window.vzConfirm({ text: T.delConfirm, danger: true, confirmText: T.del }).then(function (ok) {
            if (!ok) return;
            send(url || window.commentDeleteUrl(commentId), {}).then(function (data) {
                if (!data.ok) return;
                var el = $('comment-item-' + commentId);
                if (!el) return;
                var panel = el.closest('[id^="comment-panel-"]');
                el.remove();
                if (panel) window.updateCommentCount(panel.id.replace('comment-panel-', ''));
            }).catch(fail);
        });
    };

    /* ── Commentaires en direct : WebSocket de notifications, avec une
          interrogation HTTP de secours toutes les 45 s ─────────────────── */
    var lastId = {};
    function openPanels(fn) {
        document.querySelectorAll('.pc-comment-panel.open').forEach(function (panel) {
            var m = panel.id.match(/comment-panel-(\d+)/);
            if (m) fn(m[1]);
        });
    }
    window._onLivePostComment = function (data) {
        if (data && data.comment) appendComment(data.comment, String(data.post_id));
    };
    var prevConnected = window._notifWsConnected;
    window._notifWsConnected = function () {
        if (typeof prevConnected === 'function') prevConnected();
        openPanels(function (postId) { subscribe(postId, true); });
    };
    function pollOpenPanels() {
        if (!U.newComments) return;
        openPanels(function (postId) {
            fetch(withId(U.newComments, postId) + '?since=' + (lastId[postId] || 0),
                  { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { if (d && d.comments) d.comments.forEach(function (c) { appendComment(c, postId); }); })
                .catch(function () {});
        });
    }

    /* ── « Voir plus » ───────────────────────────────────────────────── */
    function readMoreBtn(body) {
        var btn = body.nextElementSibling;
        return btn && btn.classList.contains('pc-read-more') ? btn : null;
    }
    function setExpanded(body, on) {
        body.classList.toggle('expanded', on);
        var btn = readMoreBtn(body);
        if (btn) { btn.textContent = on ? btn.dataset.less : btn.dataset.more; btn.setAttribute('aria-expanded', on ? 'true' : 'false'); }
        if (on) return;
        var c = body.closest('.post-card');
        if (c) setTimeout(function () { c.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, 0);
    }
    window.expandBody = function (el) { setExpanded(el, !el.classList.contains('expanded')); };
    window.expandBodyBtn = function (el) {
        var body = el.previousElementSibling;
        if (body && body.classList.contains('pc-body')) window.expandBody(body);
    };
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.pc-read-more');
        if (btn) { window.expandBodyBtn(btn); return; }
        /* Toucher le texte tronqué le déplie aussi (hors liens et médias) */
        var body = e.target.closest('.pc-body');
        if (body && !body.classList.contains('expanded') && !body.classList.contains('pc-body--full')
            && !e.target.closest('a, button, video, img')) {
            var rm = readMoreBtn(body);
            if (rm && !rm.hidden) setExpanded(body, true);
        }
    });

    /* ── Hashtags et mentions ────────────────────────────────────────── */
    /* Adresse des pages hashtag (/feed/hashtag/…) : attribut data-hashtag-url du fil, sinon la configuration */
    function hashtagUrl() {
        var el = document.querySelector('[data-hashtag-url]');
        return String((el && el.getAttribute('data-hashtag-url')) || U.hashtag || '');
    }
    var SKIP = { A: 1, SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1, TEXTAREA: 1, INPUT: 1 };
    window.processHashtagsAndMentions = function (container) {
        if (!container) return;
        var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
            acceptNode: function (n) {
                for (var p = n.parentElement; p; p = p.parentElement) { if (SKIP[p.tagName]) return NodeFilter.FILTER_REJECT; }
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        var nodes = [], node;
        while ((node = walker.nextNode())) nodes.push(node);
        nodes.forEach(function (n) {
            var text = n.textContent;
            if (!/#[a-zA-ZÀ-ÿ0-9_]{2,}|@[a-zA-Z0-9_]{2,}/.test(text)) return;
            var html = esc(text)
                .replace(/#([a-zA-ZÀ-ÿ0-9_]{2,30})/g, function (m, tag) {
                    return '<a class="zf-hashtag" href="' + hashtagUrl().replace('__TAG__', encodeURIComponent(tag.toLowerCase())) + '">' + m + '</a>';
                })
                .replace(/@([a-zA-Z0-9_]{2,30})/g, function (m, user) {
                    return '<a class="zf-mention" href="' + (U.search || '') + '?q=' + encodeURIComponent(user) + '">' + m + '</a>';
                });
            var span = document.createElement('span');
            span.innerHTML = html;
            n.parentNode.replaceChild(span, n);
        });
    };
    function refreshCards() {
        document.querySelectorAll('.pc-body, .pc-title').forEach(function (el) {
            if (!el.dataset.htagDone) { el.dataset.htagDone = '1'; window.processHashtagsAndMentions(el); }
        });
        document.querySelectorAll('.pc-body').forEach(function (el) {
            if (el.classList.contains('expanded')) return;
            var rm = readMoreBtn(el);
            if (rm) rm.hidden = el.scrollHeight <= el.clientHeight + 2;
        });
        document.querySelectorAll('.pc-comment-item[id]').forEach(function (el) {
            var m = el.id.match(/comment-item-(\d+)/), panel = el.closest('[id^="comment-panel-"]');
            var pm = panel && panel.id.match(/comment-panel-(\d+)/);
            if (m && pm) lastId[pm[1]] = Math.max(lastId[pm[1]] || 0, parseInt(m[1], 10));
        });
    }
    window.vzRefreshPostCards = refreshCards;

    /* ── Autocomplétion des mentions ─────────────────────────────────── */
    var acBox = null, acTimer = null;
    function hideAc() { if (acBox) { acBox.remove(); acBox = null; } }
    function showAc(ta, users) {
        hideAc();
        var dd = document.createElement('div');
        dd.className = 'pc-mention-ac';
        users.forEach(function (u) {
            var item = document.createElement('button');
            item.type = 'button';
            item.className = 'pc-mention-ac__item';
            item.textContent = '@' + u.username;
            item.addEventListener('click', function () {
                var cursor = ta.selectionStart;
                var before = ta.value.slice(0, cursor).replace(/@([a-zA-Z0-9_]*)$/, '@' + u.username + ' ');
                ta.value = before + ta.value.slice(cursor);
                ta.setSelectionRange(before.length, before.length);
                ta.focus();
                hideAc();
            });
            dd.appendChild(item);
        });
        var rect = ta.getBoundingClientRect();
        dd.style.top = (window.scrollY + rect.bottom + 4) + 'px';
        dd.style.left = (window.scrollX + rect.left) + 'px';
        document.body.appendChild(dd);
        acBox = dd;
    }
    document.addEventListener('input', function (e) {
        var ta = e.target;
        if (!ta.classList || !(ta.classList.contains('pc-comment-textarea') || ta.classList.contains('pc-reply-textarea'))) return;
        var match = ta.value.slice(0, ta.selectionStart).match(/@([a-zA-Z0-9_]*)$/);
        clearTimeout(acTimer);
        if (!match || !U.mentions) { hideAc(); return; }
        acTimer = setTimeout(function () {
            fetch(U.mentions + '?q=' + encodeURIComponent(match[1]), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.json(); })
                .then(function (d) { if (d.users && d.users.length) showAc(ta, d.users); else hideAc(); })
                .catch(hideAc);
        }, 220);
    });
    document.addEventListener('click', function (e) { if (acBox && !acBox.contains(e.target)) hideAc(); });

    /* ── Démarrage ───────────────────────────────────────────────────── */
    function start() {
        refreshCards();
        var pending = false;
        try {
            new MutationObserver(function () {
                if (pending) return;
                pending = true;
                requestAnimationFrame(function () { pending = false; try { refreshCards(); } catch (e) {} });
            }).observe(document.querySelector('.feed-main, .vz-card-feed') || document.body, { childList: true, subtree: true });
        } catch (e) {}
        openPanels(function (postId) { subscribe(postId, true); });
        setInterval(pollOpenPanels, 45000);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
