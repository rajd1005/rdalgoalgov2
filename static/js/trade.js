function loadDetails(symId, expId, typeSelector, qtyId, slId) {
    let s = $(symId).val(); if(!s) return;
    
    let settingsKey = normalizeSymbol(s);
    
    // --- UPDATED: Determine Effective Mode ---
    // If SHADOW is selected, we must load PAPER settings for the UI form.
    let selectedMode = $('#mode_input').val();
    let mode = 'PAPER'; 
    
    if (symId === '#h_sym' || $('#history').is(':visible')) mode = 'SIMULATOR'; 
    else if (symId === '#imp_sym') mode = 'PAPER'; 
    else {
        // Map SHADOW -> PAPER for settings retrieval
        mode = (selectedMode === 'SHADOW') ? 'PAPER' : selectedMode;
    }
    
    let modeSettings = settings.modes[mode] || settings.modes.PAPER;
    
    // Update Visuals (Border/Button) if working on Main Tab
    if(symId === '#sym') updateModeVisuals(selectedMode);

    // Auto-fill SL (FIXED for Object Structure)
    if(slId) {
        let rawData = (modeSettings.symbol_sl && modeSettings.symbol_sl[settingsKey]);
        let savedSL = 20; // Default

        if (rawData) {
            if (typeof rawData === 'object') {
                // New Structure: { sl: 20, targets: [10, 20, 30] }
                savedSL = rawData.sl || 20;
            } else {
                // Legacy Structure: 20 (Number)
                savedSL = rawData;
            }
        }
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
    let rawMode = $('#mode_input').val();
    // --- UPDATED: Use PAPER Settings for Shadow ---
    let mode = (rawMode === 'SHADOW') ? 'PAPER' : rawMode;
    let modeObj = settings.modes[mode] || settings.modes.PAPER;
    let ratios = modeObj.ratios || [0.5, 1.0, 1.5];

    // --- CHECK FOR SYMBOL OVERRIDE (TARGETS) ---
    // If the user defined specific targets for this symbol, use them as ratios
    let sVal = $('#sym').val();
    if(sVal && modeObj.symbol_sl) {
        let normS = normalizeSymbol(sVal);
        let sData = modeObj.symbol_sl[normS];
        
        // Check if object structure exists and has targets
        if (sData && typeof sData === 'object' && sData.targets && sData.targets.length === 3) {
            let overrideSL = sData.sl;
            if (overrideSL > 0) {
                // Calculate implicit ratios from the saved target points
                // Ratio = TargetPoints / SLPoints
                // Note: sData.targets contains POINTS (e.g. 10, 20, 30)
                ratios = [
                    sData.targets[0] / overrideSL,
                    sData.targets[1] / overrideSL,
                    sData.targets[2] / overrideSL
                ];
            }
        }
    }
    // -------------------------------------------

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

// --- NEW FUNCTION: Update Visuals for Shadow/Live ---
function updateModeVisuals(mode) {
    let btn = $('#submit_btn');
    let card = $('#trade_form_card');
    
    // Reset classes
    btn.removeClass('btn-dark btn-danger btn-primary btn-warning btn-success');

    if (mode === "SHADOW") {
        if(card.length) card.css('border', '2px solid #6f42c1'); // Purple
        btn.text("👻 Execute Shadow Trade");
        btn.addClass('btn-dark'); // Dark/Purple style
    } else if (mode === "LIVE") {
        if(card.length) card.css('border', '1px solid red');
        btn.text("⚡ Execute LIVE Trade");
        btn.addClass('btn-danger');
    } else {
        // PAPER or others
        if(card.length) card.css('border', '1px solid #007bff'); // Blue
        btn.text("Execute Paper Trade");
        btn.addClass('btn-primary');
    }
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
    
    // --- NEW: Listener for Mode Change to Update UI Settings ---
    $('#mode_input').change(function() {
        let val = $(this).val();
        updateModeVisuals(val);
        
        // Reload details (SL/Targets) based on the new mode
        // Only trigger if a symbol is already selected to avoid blank fetches
        if($('#sym').val()) {
            loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts');
        }
    });

    // Initialize on load
    $('#ord').trigger('change');
    
    // Initialize Visuals based on default/loaded value
    updateModeVisuals($('#mode_input').val());
});
