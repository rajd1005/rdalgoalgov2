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
    let sVal = $('#sym').val(); 
    if(!sVal) return;
    if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    
    // Main Tab Fetch
    $.get('/api/specific_ltp', {
        symbol: sVal, 
        expiry: $('#exp').val(), 
        strike: $('#str').val(), 
        type: $('input[name="type"]:checked').val()
    }, function(d) {
        if(d.ltp) {
            curLTP = d.ltp; 
            $('#inst_ltp').text("LTP: " + curLTP); 
            if ($('#ord').val() === 'LIMIT' && !$('#lim_pr').val()) $('#lim_pr').val(curLTP);
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
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP;
    if(basePrice > 0) {
        let price = basePrice - pts;
        $(priceId).val(price.toFixed(2));
        calcRisk();
    }
}

function calcSLPtsFromPrice(priceId, ptsId) {
    let price = parseFloat($(priceId).val()) || 0;
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP;
    if(basePrice > 0 && price > 0) {
        let pts = basePrice - price;
        $(ptsId).val(pts.toFixed(2));
        calcRisk();
    }
}

function calcRisk() {
    let p = parseFloat($('#sl_pts').val())||0; 
    let qty = parseInt($('#qty').val())||1;
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP;
    
    if(basePrice <= 0) return;

    if (document.activeElement && document.activeElement.id !== 'p_sl') {
        let calculatedPrice = basePrice - p;
        $('#p_sl').val(calculatedPrice.toFixed(2));
    }

    // Safely get ratios
    let mode = $('#mode_input').val(); 
    let modeObj = settings.modes[mode] || settings.modes.PAPER;
    let ratios = modeObj.ratios || [0.5, 1.0, 1.5];

    let sl = basePrice - p;
    let t1 = basePrice + p * ratios[0]; 
    let t2 = basePrice + p * ratios[1]; 
    let t3 = basePrice + p * ratios[2];

    if (!document.activeElement || !['p_t1', 'p_t2', 'p_t3'].includes(document.activeElement.id)) {
        $('#p_t1').val(t1.toFixed(2)); 
        $('#p_t2').val(t2.toFixed(2)); 
        $('#p_t3').val(t3.toFixed(2));
        
        $('#pnl_t1').text(`₹ ${((t1-basePrice)*qty).toFixed(0)}`); 
        $('#pnl_t2').text(`₹ ${((t2-basePrice)*qty).toFixed(0)}`); 
        $('#pnl_t3').text(`₹ ${((t3-basePrice)*qty).toFixed(0)}`);
    }
    $('#pnl_sl').text(`₹ ${((sl-basePrice)*qty).toFixed(0)}`);
    $('#risk_disp').text("Risk: ₹ " + (p*qty).toFixed(0));

    ['t1', 't2', 't3'].forEach(k => {
        if ($(`#${k}_full`).is(':checked')) {
            $(`#${k}_lots`).val(1000).prop('readonly', true);
        } else {
            $(`#${k}_lots`).prop('readonly', false);
        }
    });
}

// --- NEW: Toggle Limit Price Requirement on Order Type Change ---
$(function() {
    $('#ord').change(function() {
        if($(this).val() === 'LIMIT') {
            $('#lim_box').show();
            $('#lim_pr').prop('required', true); // Make Mandatory
        } else {
            $('#lim_box').hide();
            $('#lim_pr').prop('required', false); // Not Mandatory for Market
        }
    });
    
    // Initialize on load
    $('#ord').trigger('change');
});
