function loadSettings() {
    $.get('/api/settings/load', function(data) {
        if(data) {
            settings = data;
            if(settings.exchanges) {
                $('input[name="exch_select"]').prop('checked', false);
                settings.exchanges.forEach(e => $(`#exch_${e}`).prop('checked', true));
            }
            
            // --- NEW: Load Broadcast Defaults ---
            // 1. Set values in Settings Modal (General Tab)
            let defaults = settings.broadcast_defaults || ['vip', 'free', 'z2h'];
            $('#def_vip').prop('checked', defaults.includes('vip'));
            $('#def_free').prop('checked', defaults.includes('free'));
            $('#def_z2h').prop('checked', defaults.includes('z2h'));

            // 2. APPLY Defaults to Dashboard Trade Panel (if elements exist)
            if($('#chk_vip').length) $('#chk_vip').prop('checked', defaults.includes('vip'));
            if($('#chk_free').length) $('#chk_free').prop('checked', defaults.includes('free'));
            if($('#chk_z2h').length) $('#chk_z2h').prop('checked', defaults.includes('z2h'));
            // ------------------------------------

            renderWatchlist();
            ['PAPER', 'LIVE'].forEach(m => {
                let k = m.toLowerCase();
                let s = settings.modes[m];
                $(`#${k}_qty_mult`).val(s.qty_mult);
                
                // Ratios
                $(`#${k}_r1`).val(s.ratios[0]);
                $(`#${k}_r2`).val(s.ratios[1]);
                $(`#${k}_r3`).val(s.ratios[2]);
                
                // Trailing SL & Defaults
                $(`#${k}_def_trail`).val(s.trailing_sl || 0);
                $(`#${k}_order_type`).val(s.order_type || 'MARKET');
                $(`#${k}_trail_limit`).val(s.sl_to_entry || 0);
                $(`#${k}_exit_mult`).val(s.exit_multiplier || 1);
                
                // --- NEW RISK SETTINGS ---
                $(`#${k}_time`).val(s.universal_exit_time || "15:25");
                $(`#${k}_max_loss`).val(s.max_loss || 0);
                $(`#${k}_pl_start`).val(s.profit_lock || 0);
                $(`#${k}_pl_min`).val(s.profit_min || 0);
                $(`#${k}_pl_trail`).val(s.profit_trail || 0);

                // Target Config
                let tgts = s.targets || [
                    {active: true, lots: 0, full: false, trail_to_entry: false},
                    {active: true, lots: 0, full: false, trail_to_entry: false},
                    {active: true, lots: 1000, full: true, trail_to_entry: false}
                ];
                
                // T1
                $(`#${k}_a1`).prop('checked', tgts[0].active);
                $(`#${k}_l1`).val(tgts[0].lots > 0 && !tgts[0].full ? tgts[0].lots : '');
                $(`#${k}_f1`).prop('checked', tgts[0].full);
                $(`#${k}_c1`).prop('checked', tgts[0].trail_to_entry || false);
                
                // T2
                $(`#${k}_a2`).prop('checked', tgts[1].active);
                $(`#${k}_l2`).val(tgts[1].lots > 0 && !tgts[1].full ? tgts[1].lots : '');
                $(`#${k}_f2`).prop('checked', tgts[1].full);
                $(`#${k}_c2`).prop('checked', tgts[1].trail_to_entry || false);

                // T3
                $(`#${k}_a3`).prop('checked', tgts[2].active);
                $(`#${k}_l3`).val(tgts[2].lots > 0 && !tgts[2].full ? tgts[2].lots : '');
                $(`#${k}_f3`).prop('checked', tgts[2].full);
                $(`#${k}_c3`).prop('checked', tgts[2].trail_to_entry || false);

                renderSLTable(m);
            });

            // --- LOAD TELEGRAM SETTINGS (UPDATED) ---
            if(settings.telegram) {
                $('#tg_bot_token').val(settings.telegram.bot_token || '');
                $('#tg_enable').prop('checked', settings.telegram.enable_notifications || false);
                
                // Main & System
                $('#tg_channel_id').val(settings.telegram.channel_id || '');
                $('#tg_system_channel_id').val(settings.telegram.system_channel_id || ''); 
                
                // Extra Channels
                $('#tg_vip_channel_id').val(settings.telegram.vip_channel_id || '');
                $('#tg_free_channel_id').val(settings.telegram.free_channel_id || '');
                $('#tg_z2h_channel_id').val(settings.telegram.z2h_channel_id || '');
                $('#tg_z2h_channel_name').val(settings.telegram.z2h_channel_name || 'Zero To Hero');
            }

            if (typeof updateDisplayValues === "function") updateDisplayValues(); 
        }
    });
}

function saveSettings() {
    let selectedExchanges = [];
    $('input[name="exch_select"]:checked').each(function() { selectedExchanges.push($(this).val()); });
    settings.exchanges = selectedExchanges;

    // --- NEW: Save Broadcast Defaults ---
    let b_defs = [];
    if($('#def_vip').is(':checked')) b_defs.push('vip');
    if($('#def_free').is(':checked')) b_defs.push('free');
    if($('#def_z2h').is(':checked')) b_defs.push('z2h');
    settings.broadcast_defaults = b_defs;
    // ------------------------------------

    ['PAPER', 'LIVE'].forEach(m => {
        let k = m.toLowerCase();
        let s = settings.modes[m];
        
        s.qty_mult = parseInt($(`#${k}_qty_mult`).val()) || 1;
        s.ratios = [parseFloat($(`#${k}_r1`).val()), parseFloat($(`#${k}_r2`).val()), parseFloat($(`#${k}_r3`).val())];
        s.trailing_sl = parseFloat($(`#${k}_def_trail`).val()) || 0;
        
        // Save Defaults
        s.order_type = $(`#${k}_order_type`).val();
        s.sl_to_entry = parseInt($(`#${k}_trail_limit`).val()) || 0;
        s.exit_multiplier = parseInt($(`#${k}_exit_mult`).val()) || 1;
        
        // --- SAVE NEW RISK SETTINGS ---
        s.universal_exit_time = $(`#${k}_time`).val();
        s.max_loss = parseFloat($(`#${k}_max_loss`).val()) || 0;
        s.profit_lock = parseFloat($(`#${k}_pl_start`).val()) || 0;
        s.profit_min = parseFloat($(`#${k}_pl_min`).val()) || 0;
        s.profit_trail = parseFloat($(`#${k}_pl_trail`).val()) || 0;
        
        // Save Target Configs
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

    // --- SAVE TELEGRAM SETTINGS (UPDATED) ---
    settings.telegram = {
        bot_token: $('#tg_bot_token').val().trim(),
        enable_notifications: $('#tg_enable').is(':checked'),
        
        channel_id: $('#tg_channel_id').val().trim(),
        system_channel_id: $('#tg_system_channel_id').val().trim(),
        
        // Save Extra Channels
        vip_channel_id: $('#tg_vip_channel_id').val().trim(),
        free_channel_id: $('#tg_free_channel_id').val().trim(),
        z2h_channel_id: $('#tg_z2h_channel_id').val().trim(),
        z2h_channel_name: $('#tg_z2h_channel_name').val().trim() || 'Zero To Hero'
    };

    $.ajax({ 
        type: "POST", 
        url: '/api/settings/save', 
        data: JSON.stringify(settings), 
        contentType: "application/json", 
        success: () => { 
            $('#settingsModal').modal('hide'); 
            loadSettings(); // Reload to apply new defaults to dashboard immediately
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
function editSymSL(mode, sym) { let k = mode.toLowerCase(); $(`#${k}_set_sym`).val(sym); $(`#${k}_set_sl`).val(settings.modes[mode].symbol_sl[sym]); }
function deleteSymSL(mode, sym) { delete settings.modes[mode].symbol_sl[sym]; renderSLTable(mode); }
