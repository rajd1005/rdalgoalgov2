// Global variables for trade context (assumed to be used across the app)
var curLTP = 0;
var curLotSize = 1;
var symLTP = {};

function loadDetails(symId, expId, typeSelector, qtyId, slId) {
    let s = $(symId).val(); if(!s) return;
    
    let settingsKey = normalizeSymbol(s);
    let mode = 'PAPER'; 
    
    if (symId === '#h_sym' || $('#history').is(':visible')) mode = 'SIMULATOR'; 
    else if (symId === '#imp_sym') mode = 'PAPER'; 
    else mode = $('#mode_input').val();
    
    let modeSettings = settings.modes[mode] || settings.modes.PAPER;
    
    // Auto-fill SL
    if(slId) {
        let savedSL = (modeSettings.symbol_sl && modeSettings.symbol_sl[settingsKey]) || 20;
        $(slId).val(savedSL);
    }
    
    // Auto-fill Settings
    if(mode !== 'SIMULATOR') {
        let prefix = (symId === '#imp_sym') ? '#imp_' : '#'; 
        let trailVal = modeSettings.trailing_sl || 0;
        
        if(prefix === '#imp_') {
             $('#imp_trail_sl').val(trailVal);
             $('#imp_trail_limit').val(modeSettings.sl_to_entry || 0);
             $('#imp_exit_mult').val(modeSettings.exit_multiplier || 1);
             
             if(modeSettings.targets) {
                ['t1', 't2', 't3'].forEach((k, i) => {
                    let conf = modeSettings.targets[i];
                    $(`#imp_${k}_active`).prop('checked', conf.active);
                    $(`#imp_${k}_full`).prop('checked', conf.full);
                    $(`#imp_${k}_cost`).prop('checked', conf.trail_to_entry || false);
                    if(conf.full) $(`#imp_${k}_lots`).val(1000);
                    else $(`#imp_${k}_lots`).val(conf.lots > 0 ? conf.lots : '');
                });
             }
        } else {
             $('#trail_sl').val(trailVal);
             $('#ord').val(modeSettings.order_type || 'MARKET').trigger('change');
             $('select[name="sl_to_entry"]').val(modeSettings.sl_to_entry || 0);
             $('#exit_mult').val(modeSettings.exit_multiplier || 1);
             
             if(modeSettings.targets) {
                ['t1', 't2', 't3'].forEach((k, i) => {
                    let conf = modeSettings.targets[i];
                    $(`#${k}_active`).prop('checked', conf.active);
                    $(`#${k}_full`).prop('checked', conf.full);
                    $(`input[name="${k}_cost"]`).prop('checked', conf.trail_to_entry || false);
                    
                    if(conf.full) $(`#${k}_lots`).val(1000);
                    else $(`#${k}_lots`).val(conf.lots > 0 ? conf.lots : '');
                });
             }
        }
    }
    
    if(mode === 'SIMULATOR' && typeof calcSimSL === 'function') calcSimSL('pts'); 
    else if (symId !== '#imp_sym') calcRisk(); 

    $.get('/api/details', {symbol: s}, function(d) { 
        symLTP[symId] = d.ltp; 
        
        // Update Import Modal
        if(symId === '#imp_sym') {
            $('#imp_ltp').text("LTP: " + d.ltp);
            if(!$('#imp_price').val()) {
                $('#imp_price').val(d.ltp);
                if($('#imp_sl_pts').val() > 0) $('#imp_sl_pts').trigger('input');
            }
        }

        if(d.lot_size > 0) {
            curLotSize = d.lot_size;
            if(symId !== '#imp_sym') $('#lot').text(curLotSize); 
            
            let mult = parseInt(modeSettings.qty_mult) || 1;
            $(qtyId).val(curLotSize * mult).attr('step', curLotSize).attr('min', curLotSize);
        }
        window[symId+'_fut'] = d.fut_expiries; 
        window[symId+'_opt'] = d.opt_expiries;
        
        let typeVal = $(typeSelector).val();
        if (typeVal) fillExp(expId, typeSelector, symId);
        else {
            $(expId).empty();
            let strId = (expId === '#exp') ? '#str' : (expId === '#imp_exp' ? '#imp_str' : '#h_str');
            $(strId).empty().append('<option>Select Type First</option>');
        }
    });
}

function adjQty(inputId, dir) {
    let val = parseInt($(inputId).val()) || curLotSize;
    let step = curLotSize;
    let newVal = val + (dir * step);
    if(newVal >= step) {
        $(inputId).val(newVal).trigger('input');
    }
}

function fillExp(expId, typeSelector, symId) { 
    let typeVal = $(typeSelector).val();
    let l = typeVal=='FUT' ? window[symId+'_fut'] : window[symId+'_opt']; 
    let $e = $(expId).empty(); 
    if(l) l.forEach(d => $e.append(`<option value="${d}">${d}</option>`)); 
    
    if(expId === '#exp') fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str');
    if(expId === '#h_exp') fillChain('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_str');
    if(expId === '#imp_exp') fillChain('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_str');
}

function fillChain(sym, exp, typeSelector, str) {
    let spot = symLTP[sym] || 0; 
    let sVal = $(sym).val(); if(!sVal) return;
    if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    
    $.get('/api/chain', {
        symbol: sVal, 
        expiry: $(exp).val(), 
        type: $(typeSelector).val(), 
        ltp: spot
    }, function(d) {
        let $s = $(str).empty(); 
        d.forEach(r => { 
            let style = r.label.includes('ATM') ? 'style="color:red; font-weight:bold;"' : ''; 
            let selected = r.label.includes('ATM') ? 'selected' : ''; 
            let mark = r.label.includes('ATM') ? '🔴' : '';
            $s.append(`<option value="${r.strike}" ${selected} ${style}>${mark} ${r.strike} ${r.label}</option>`); 
        });
        if(sym === '#imp_sym') fetchLTP();
    });
}

function fetchLTP() {
    let sVal = $('#trade_sym').val(); 
    if(!sVal) return;
    if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    
    // Main Tab Fetch
    $.get('/api/specific_ltp', {
        symbol: sVal, 
        expiry: $('#trade_exp').val(), 
        strike: $('#trade_str').val(), 
        type: $('input[name="trade_type"]:checked').val()
    }, function(d) {
        if(d.ltp) {
            curLTP = d.ltp; 
            $('#trade_ltp').text("LTP: " + curLTP); 
            if ($('#trade_price').val() === '' && $('#trade_sl').val() !== '') calcRisk();
            calcRisk();
        }
    });

    // Import Modal Fetch
    if($('#importModal').is(':visible')) {
        let iSym = $('#imp_sym').val();
        if(iSym && $('#imp_exp').val() && $('#imp_str').val()) {
            $.get('/api/specific_ltp', {
                symbol: iSym, 
                expiry: $('#imp_exp').val(), 
                strike: $('#imp_str').val(), 
                type: $('input[name="imp_type"]:checked').val()
            }, function(d) {
                if(d.ltp > 0) {
                    $('#imp_ltp').text("LTP: "+d.ltp);
                    if(!$('#imp_price').val()) $('#imp_price').val(d.ltp);
                }
            });
        }
    }
}

function calcSLPriceFromPts(ptsId, priceId) {
    let pts = parseFloat($(ptsId).val()) || 0;
    let basePrice = curLTP;
    // If limit price is set and order type is LIMIT, use that
    // Note: ID for price input in trade tab is trade_price
    let limitInput = parseFloat($('#trade_price').val());
    if(limitInput > 0) basePrice = limitInput;

    if(basePrice > 0) {
        let price = basePrice - pts;
        $(priceId).val(price.toFixed(2));
        calcRisk();
    }
}

function calcSLPtsFromPrice(priceId, ptsId) {
    let price = parseFloat($(priceId).val()) || 0;
    let basePrice = curLTP;
    let limitInput = parseFloat($('#trade_price').val());
    if(limitInput > 0) basePrice = limitInput;

    if(basePrice > 0 && price > 0) {
        let pts = basePrice - price;
        $(ptsId).val(pts.toFixed(2));
        calcRisk();
    }
}

function calcRisk() {
    let p = parseFloat($('#trade_sl').val())||0; 
    let qty = parseInt($('#trade_qty').val())||1;
    let basePrice = curLTP;
    let limitInput = parseFloat($('#trade_price').val());
    if(limitInput > 0) basePrice = limitInput;
    
    if(basePrice <= 0) return;

    // We no longer display calculated SL price in a separate read-only field in the new UI structure
    // but if we did, it would go here.

    // Safely get ratios
    let mode = $('#mode_input').val(); // Assuming mode_input exists in main layout
    if(!mode) mode = 'PAPER'; // Default fallback

    let modeObj = (settings && settings.modes) ? (settings.modes[mode] || settings.modes.PAPER) : {};
    let ratios = modeObj.ratios || [0.5, 1.0, 1.5];

    let sl = basePrice - p;
    let t1 = basePrice + p * ratios[0]; 
    let t2 = basePrice + p * ratios[1]; 
    let t3 = basePrice + p * ratios[2];

    // If inputs are not being edited manually, auto-fill them
    if (document.activeElement && document.activeElement.id !== 'trade_t1') $('#trade_t1').val(t1.toFixed(2));
    if (document.activeElement && document.activeElement.id !== 'trade_t2') $('#trade_t2').val(t2.toFixed(2));
    if (document.activeElement && document.activeElement.id !== 'trade_t3') $('#trade_t3').val(t3.toFixed(2));
    
    // Manage readonly states for full exit
    ['t1', 't2', 't3'].forEach(k => {
        if ($(`#trade_${k}_full`).is(':checked')) {
            $(`#trade_${k}_lots`).val(1000).prop('readonly', true);
        } else {
            $(`#trade_${k}_lots`).prop('readonly', false);
        }
    });
}

/**
 * NEW: Renders the channel selector checkboxes based on global settings.
 * This should be called after settings are loaded.
 */
function renderChannelSelector() {
    let container = $('#channel_selector');
    if(!container.length) return; // Guard if element doesn't exist
    
    container.empty();
    
    // 1. Always add Main Channel (Checked by default)
    container.append(`
        <div class="form-check form-check-inline">
            <input class="form-check-input" type="checkbox" name="notify_main" id="notify_main" checked>
            <label class="form-check-label" style="font-size:0.8rem; font-weight:600;" for="notify_main">Main</label>
        </div>
    `);

    // 2. Add Extra Channels if enabled in settings
    if(settings && settings.telegram && settings.telegram.extra_channels) {
        settings.telegram.extra_channels.forEach(ch => {
            if(ch.enabled && ch.chat_id) {
                container.append(`
                    <div class="form-check form-check-inline">
                        <input class="form-check-input" type="checkbox" name="notify_${ch.id}" id="notify_${ch.id}">
                        <label class="form-check-label" style="font-size:0.8rem;" for="notify_${ch.id}">${ch.name}</label>
                    </div>
                `);
            }
        });
    }
}

/**
 * Executes the trade by gathering all form data including new channels.
 * @param {string} direction - 'BUY' or 'SELL'
 */
function placeTrade(direction) {
    // 1. Basic Validation
    let sym = $('#trade_sym').val();
    if(!sym) { alert("Please enter a symbol"); return; }
    
    let qty = parseInt($('#trade_qty').val());
    if(!qty || qty <= 0) { alert("Invalid Quantity"); return; }
    
    // 2. Gather Data
    let data = {
        symbol: sym,
        exchange: "NFO", // Default, could be derived from watchlist metadata
        type: $('input[name="trade_type"]:checked').val(),
        expiry: $('#trade_exp').val(),
        strike: $('#trade_str').val(),
        qty: qty,
        direction: direction,
        price: parseFloat($('#trade_price').val()) || 0, // 0 = Market
        sl_points: parseFloat($('#trade_sl').val()) || 0,
        sl_price: parseFloat($('#trade_sl_price').val()) || 0,
        
        // Settings / Context
        mode: $('#mode_input').val(),
        exit_multiplier: $('#trade_exit_mult').val() || 1,
        
        // Targets Configuration
        t1_price: $('#trade_t1').val(),
        t1_active: $('#trade_t1_active').is(':checked'),
        t1_lots: $('#trade_t1_full').is(':checked') ? 1000 : ($('#trade_t1_lots').val() || 0),
        t1_cost: $('#trade_t1_cost').is(':checked'),
        
        t2_price: $('#trade_t2').val(),
        t2_active: $('#trade_t2_active').is(':checked'),
        t2_lots: $('#trade_t2_full').is(':checked') ? 1000 : ($('#trade_t2_lots').val() || 0),
        t2_cost: $('#trade_t2_cost').is(':checked'),
        
        t3_price: $('#trade_t3').val(),
        t3_active: $('#trade_t3_active').is(':checked'),
        t3_lots: $('#trade_t3_full').is(':checked') ? 1000 : ($('#trade_t3_lots').val() || 0),
        t3_cost: $('#trade_t3_cost').is(':checked'),
    };

    // 3. NEW: Collect Notification Channels
    data.notify_main = $('#notify_main').is(':checked') ? 'on' : 'off';
    
    // Check extra channels
    if(settings && settings.telegram && settings.telegram.extra_channels) {
        settings.telegram.extra_channels.forEach(ch => {
            if($(`#notify_${ch.id}`).is(':checked')) {
                data[`notify_${ch.id}`] = 'on';
            }
        });
    }

    // 4. Send Request
    let btn = event.target; 
    let originalText = $(btn).html();
    $(btn).prop('disabled', true).text('Processing...');

    $.ajax({
        type: "POST",
        url: "/trade",
        data: data,
        success: function(res) {
            $(btn).prop('disabled', false).html(originalText);
            if(res.status === 'success') {
                alert("✅ Order Placed Successfully!");
                // Optionally clear form or refresh positions
                if(typeof updateData === 'function') updateData(); // Trigger immediate refresh
            } else {
                alert("❌ Error: " + res.message);
            }
        },
        error: function(err) {
            $(btn).prop('disabled', false).html(originalText);
            alert("❌ Server Error: " + err.statusText);
        }
    });
}
