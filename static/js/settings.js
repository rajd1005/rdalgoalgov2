function loadSettings() {
    $.get('/api/settings/load', function(data) {
        if(data) {
            settings = data;
            
            // --- Exchanges ---
            if(settings.exchanges) {
                $('input[name="exch_select"]').prop('checked', false);
                settings.exchanges.forEach(e => $(`#exch_${e}`).prop('checked', true));
            }
            
            // --- NEW: Default Trade Mode ---
            // 1. Set Value in Settings Modal
            let defMode = settings.default_trade_mode || 'PAPER';
            $('#def_trade_mode').val(defMode);

            // 2. Apply to Dashboard (Auto-Click the Mode Button)
            // We find the button that sets this mode and click it if it's not active
            let btn = $(`button[onclick*="setMode"][onclick*="'${defMode}'"]`);
            if(btn.length && !btn.hasClass('active')) {
                btn.click();
            }
            // -------------------------------

            // --- Broadcast Defaults ---
            let defaults = settings.broadcast_defaults || ['vip', 'free', 'z2h'];
            $('#def_vip').prop('checked', defaults.includes('vip'));
            $('#def_free').prop('checked', defaults.includes('free'));
            $('#def_z2h').prop('checked', defaults.includes('z2h'));

            // Apply to Dashboard Panel if present
            if($('#chk_vip').length) $('#chk_vip').prop('checked', defaults.includes('vip'));
            if($('#chk_free').length) $('#chk_free').prop('checked', defaults.includes('free'));
            if($('#chk_z2h').length) $('#chk_z2h').prop('checked', defaults.includes('z2h'));

            renderWatchlist();

            // --- Modes (PAPER / LIVE) ---
            ['PAPER', 'LIVE'].forEach(m => {
                let k = m.toLowerCase();
                let s = settings.modes[m];
                
                $(`#${k}_qty_mult`).val(s.qty_mult);
                $(`#${k}_r1`).val(s.ratios[0]);
                $(`#${k}_r2`).val(s.ratios[1]);
                $(`#${k}_r3`).val(s.ratios[2]);
                $(`#${k}_def_trail`).val(s.trailing_sl || 0);
                $(`#${k}_order_type`).val(s.order_type || 'MARKET');
                $(`#${k}_trail_limit`).val(s.sl_to_entry || 0);
                $(`#${k}_exit_mult`).val(s.exit_multiplier || 1);
                $(`#${k}_time`).val(s.universal_exit_time || "15:25");
                $(`#${k}_max_loss`).val(s.max_loss || 0);
                $(`#${k}_pl_start`).val(s.profit_lock || 0);
                $(`#${k}_pl_min`).val(s.profit_min || 0);
                $(`#${k}_pl_trail`).val(s.profit_trail || 0);

                let tgts = s.targets || [
                    {active: true, lots: 0, full: false, trail_to_entry: false},
                    {active: true, lots: 0, full: false, trail_to_entry: false},
                    {active: true, lots: 1000, full: true, trail_to_entry: false}
                ];
                
                $(`#${k}_a1`).prop('checked', tgts[0].active);
                $(`#${k}_l1`).val(tgts[0].lots > 0 && !tgts[0].full ? tgts[0].lots : '');
                $(`#${k}_f1`).prop('checked', tgts[0].full);
                $(`#${k}_c1`).prop('checked', tgts[0].trail_to_entry || false);
                
                $(`#${k}_a2`).prop('checked', tgts[1].active);
                $(`#${k}_l2`).val(tgts[1].lots > 0 && !tgts[1].full ? tgts[1].lots : '');
                $(`#${k}_f2`).prop('checked', tgts[1].full);
                $(`#${k}_c2`).prop('checked', tgts[1].trail_to_entry || false);

                $(`#${k}_a3`).prop('checked', tgts[2].active);
                $(`#${k}_l3`).val(tgts[2].lots > 0 && !tgts[2].full ? tgts[2].lots : '');
                $(`#${k}_f3`).prop('checked', tgts[2].full);
                $(`#${k}_c3`).prop('checked', tgts[2].trail_to_entry || false);

                renderSLTable(m);
            });

            // --- Telegram Settings ---
            if(settings.telegram) {
                $('#tg_bot_token').val(settings.telegram.bot_token || '');
                $('#tg_enable').prop('checked', settings.telegram.enable_notifications || false);
                $('#tg_channel_id').val(settings.telegram.channel_id || '');
                $('#tg_system_channel_id').val(settings.telegram.system_channel_id || ''); 
                $('#tg_vip_channel_id').val(settings.telegram.vip_channel_id || '');
                $('#tg_free_channel_id').val(settings.telegram.free_channel_id || '');
                $('#tg_z2h_channel_id').val(settings.telegram.z2h_channel_id || '');
                $('#tg_z2h_channel_name').val(settings.telegram.z2h_channel_name || 'Zero To Hero');

                let toggles = settings.telegram.event_toggles || {};
                $('#tg_evt_new').prop('checked', toggles.NEW_TRADE !== false);
                $('#tg_evt_active').prop('checked', toggles.ACTIVE !== false);
                $('#tg_evt_update').prop('checked', toggles.UPDATE !== false);
                $('#tg_evt_sl').prop('checked', toggles.SL_HIT !== false);
                $('#tg_evt_tgt').prop('checked', toggles.TARGET_HIT !== false);
                $('#tg_evt_high').prop('checked', toggles.HIGH_MADE !== false);

                let tpls = settings.telegram.templates || {};
                $('#tpl_new').val(tpls.NEW_TRADE || "");
                $('#tpl_active').val(tpls.ACTIVE || "");
                $('#tpl_update').val(tpls.UPDATE || "");
                $('#tpl_sl').val(tpls.SL_HIT || "");
                $('#tpl_tgt').val(tpls.TARGET_HIT || "");
                $('#tpl_high').val(tpls.HIGH_MADE || "");
                $('#tpl_free_header').val(tpls.FREE_HEADER || ""); 
            }

            if (typeof updateDisplayValues === "function") updateDisplayValues(); 
        }
    });
}

function saveSettings() {
    // Exchanges
    let selectedExchanges = [];
    $('input[name="exch_select"]:checked').each(function() { selectedExchanges.push($(this).val()); });
    settings.exchanges = selectedExchanges;

    // Default Trade Mode
    settings.default_trade_mode = $('#def_trade_mode').val(); // <--- SAVE NEW SETTING

    // Broadcast Defaults
    let b_defs = [];
    if($('#def_vip').is(':checked')) b_defs.push('vip');
    if($('#def_free').is(':checked')) b_defs.push('free');
    if($('#def_z2h').is(':checked')) b_defs.push('z2h');
    settings.broadcast_defaults = b_defs;

    // Modes
    ['PAPER', 'LIVE'].forEach(m => {
        let k = m.toLowerCase();
        let s = settings.modes[m];
        
        s.qty_mult = parseInt($(`#${k}_qty_mult`).val()) || 1;
        s.ratios = [parseFloat($(`#${k}_r1`).val()), parseFloat($(`#${k}_r2`).val()), parseFloat($(`#${k}_r3`).val())];
        s.trailing_sl = parseFloat($(`#${k}_def_trail`).val()) || 0;
        
        s.order_type = $(`#${k}_order_type`).val();
        s.sl_to_entry = parseInt($(`#${k}_trail_limit`).val()) || 0;
        s.exit_multiplier = parseInt($(`#${k}_exit_mult`).val()) || 1;
        
        s.universal_exit_time = $(`#${k}_time`).val();
        s.max_loss = parseFloat($(`#${k}_max_loss`).val()) || 0;
        s.profit_lock = parseFloat($(`#${k}_pl_start`).val()) || 0;
        s.profit_min = parseFloat($(`#${k}_pl_min`).val()) || 0;
        s.profit_trail = parseFloat($(`#${k}_pl_trail`).val()) || 0;
        
        s.targets = [
            {
                active: $(`#${k}_a1`).is(':checked'),
                full: $(`#${k}_f1`).is(':checked'),
                lots: $(`#${k}_f1`).is(':checked') ? 1000 : (parseInt($(`#${k}_l1`).val()) || 0),
                trail_to_entry: $(`#${k}_c1`).is(':checked')
            },
            {
                active: $(`#${k}_a2`).is(':checked'),
                full: $(`#${k}_f2`).is(':checked'),
                lots: $(`#${k}_f2`).is(':checked') ? 1000 : (parseInt($(`#${k}_l2`).val()) || 0),
                trail_to_entry: $(`#${k}_c2`).is(':checked')
            },
            {
                active: $(`#${k}_a3`).is(':checked'),
                full: $(`#${k}_f3`).is(':checked'),
                lots: $(`#${k}_f3`).is(':checked') ? 1000 : (parseInt($(`#${k}_l3`).val()) || 0),
                trail_to_entry: $(`#${k}_c3`).is(':checked')
            }
        ];
    });

    // Telegram
    settings.telegram = {
        bot_token: $('#tg_bot_token').val().trim(),
        enable_notifications: $('#tg_enable').is(':checked'),
        
        channel_id: $('#tg_channel_id').val().trim(),
        system_channel_id: $('#tg_system_channel_id').val().trim(),
        vip_channel_id: $('#tg_vip_channel_id').val().trim(),
        free_channel_id: $('#tg_free_channel_id').val().trim(),
        z2h_channel_id: $('#tg_z2h_channel_id').val().trim(),
        z2h_channel_name: $('#tg_z2h_channel_name').val().trim() || 'Zero To Hero',

        event_toggles: {
            NEW_TRADE: $('#tg_evt_new').is(':checked'),
            ACTIVE: $('#tg_evt_active').is(':checked'),
            UPDATE: $('#tg_evt_update').is(':checked'),
            SL_HIT: $('#tg_evt_sl').is(':checked'),
            TARGET_HIT: $('#tg_evt_tgt').is(':checked'),
            HIGH_MADE: $('#tg_evt_high').is(':checked')
        },

        templates: {
            NEW_TRADE: $('#tpl_new').val(),
            ACTIVE: $('#tpl_active').val(),
            UPDATE: $('#tpl_update').val(),
            SL_HIT: $('#tpl_sl').val(),
            TARGET_HIT: $('#tpl_tgt').val(),
            HIGH_MADE: $('#tpl_high').val(),
            FREE_HEADER: $('#tpl_free_header').val()
        }
    };

    $.ajax({ 
        type: "POST", 
        url: '/api/settings/save', 
        data: JSON.stringify(settings), 
        contentType: "application/json", 
        success: () => { 
            $('#settingsModal').modal('hide'); 
            loadSettings(); 
        } 
    });
}

function testTelegram() {
    let token = $('#tg_bot_token').val().trim();
    let chat = $('#tg_channel_id').val().trim();
    
    if(!token || !chat) { alert("Enter Token & Main Channel ID first"); return; }
    
    $.post('/api/test_telegram', { token: token, chat_id: chat }, function(res) {
        if(res.status === 'success') alert("✅ Message Sent Successfully!");
        else alert("❌ Error: " + res.message);
    });
}

function renderWatchlist() {
    let wl = settings.watchlist || [];
    let opts = '<option value="">📺 Select</option>';
    wl.forEach(w => { opts += `<option value="${w}">${w}</option>`; });
    $('#trade_watch').html(opts);
    if($('#imp_watch').length) $('#imp_watch').html(opts);
}

function addToWatchlist(inputId) {
    let val = $(inputId).val();
    if(val && val.length > 2) {
        if(val.includes('(')) val = val.split('(')[0].trim();
        else if(val.includes(':')) val = val.split(':')[0].trim();
        
        if(!settings.watchlist) settings.watchlist = [];
        if(!settings.watchlist.includes(val)) {
            settings.watchlist.push(val);
            $.ajax({ 
                type: "POST", 
                url: '/api/settings/save', 
                data: JSON.stringify(settings), 
                contentType: "application/json", 
                success: () => { 
                    renderWatchlist();
                    let btn = $(inputId).next(); let originalText = btn.text(); btn.text("✅"); setTimeout(() => btn.text(originalText), 1000);
                }
            });
        } else { alert("Symbol already in Watchlist"); }
    }
}

function removeFromWatchlist(selectId) {
    let val = $('#' + selectId).val();
    if(val) {
        if(confirm("Remove " + val + " from watchlist?")) {
            settings.watchlist = settings.watchlist.filter(item => item !== val);
            $.ajax({ type: "POST", url: '/api/settings/save', data: JSON.stringify(settings), contentType: "application/json", success: () => { renderWatchlist(); }});
        }
    }
}

function loadWatchlist(selectId, inputId) {
    let val = $('#' + selectId).val();
    if(val) {
        $(inputId).val(val).trigger('change');
        $(inputId).trigger('input'); 
    }
}

function applyBulkSL(mode) {
    let k = mode.toLowerCase();
    let text = $(`#${k}_bulk_sl`).val();
    if(!text) { alert("Please enter SYMBOL|SL"); return; }
    let lines = text.split('\n'); let count = 0;
    if(!settings.modes[mode].symbol_sl) settings.modes[mode].symbol_sl = {};
    lines.forEach(l => {
        let parts = l.split('|');
        if(parts.length === 2) {
            let s = normalizeSymbol(parts[0]); let v = parseInt(parts[1].trim());
            if(s && v > 0) { settings.modes[mode].symbol_sl[s] = v; count++; }
        }
    });
    renderSLTable(mode); $(`#${k}_bulk_sl`).val('');
    alert(`Successfully updated ${count} symbols for ${mode}. Click Save Changes.`);
}

function renderSLTable(mode) {
    let k = mode.toLowerCase();
    let tbody = $(`#${k}_sl_table_body`).empty();
    let slMap = settings.modes[mode].symbol_sl || {};
    Object.keys(slMap).forEach(sym => {
        tbody.append(`<tr><td class="fw-bold">${sym}</td><td>${slMap[sym]}</td><td><button class="btn btn-sm btn-outline-secondary py-0" onclick="editSymSL('${mode}', '${sym}')">✏️</button> <button class="btn btn-sm btn-outline-danger py-0" onclick="deleteSymSL('${mode}', '${sym}')">🗑️</button></td></tr>`);
    });
}

function saveSymSL(mode) {
    let k = mode.toLowerCase();
    let s = normalizeSymbol($(`#${k}_set_sym`).val());
    let p = parseInt($(`#${k}_set_sl`).val());
    if(s && p) {
        if(!settings.modes[mode].symbol_sl) settings.modes[mode].symbol_sl = {};
        settings.modes[mode].symbol_sl[s] = p;
        renderSLTable(mode);
        $(`#${k}_set_sym`).val(''); $(`#${k}_set_sl`).val('');
    }
}

function editSymSL(mode, sym) { 
    let k = mode.toLowerCase(); 
    $(`#${k}_set_sym`).val(sym); 
    $(`#${k}_set_sl`).val(settings.modes[mode].symbol_sl[sym]); 
}

function deleteSymSL(mode, sym) { 
    delete settings.modes[mode].symbol_sl[sym]; 
    renderSLTable(mode); 
}
