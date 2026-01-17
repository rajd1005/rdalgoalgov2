$(document).ready(function() {
    // --- CONFIGURATION ---
    const REFRESH_INTERVAL = 500; // Update Interval in milliseconds (1000ms = 1 second)
    // ---------------------

    renderWatchlist();
    loadSettings();
    
    let now = new Date(); const offset = now.getTimezoneOffset(); let localDate = new Date(now.getTime() - (offset*60*1000));
    $('#hist_date').val(localDate.toISOString().slice(0,10)); 
    
    // Global Bindings
    $('#hist_date, #hist_filter').change(loadClosedTrades);
    $('#active_filter').change(updateData);
    
    $('input[name="type"]').change(function() {
        let s = $('#sym').val();
        if(s) loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts');
    });
    
    $('#sl_pts, #qty, #lim_pr, #ord').on('input change', calcRisk);
    
    // Bind Search Logic
    bindSearch('#sym', '#sym_list'); 
    bindSearch('#imp_sym', '#sym_list'); 

    // Chain & input Bindings
    $('#sym').change(() => loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'));
    $('#exp').change(() => fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str'));
    $('#ord').change(function() { if($(this).val() === 'LIMIT') $('#lim_box').show(); else $('#lim_box').hide(); });
    $('#str').change(fetchLTP);

    // Import Modal Bindings
    $('#imp_sym').change(() => loadDetails('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_qty', '#imp_sl_pts')); 
    $('#imp_exp').change(() => fillChain('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_str'));
    $('input[name="imp_type"]').change(() => loadDetails('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_qty', '#imp_sl_pts'));
    
    // Import Risk Calc Bindings
    $('#imp_price').on('input', function() { calcImpFromPts(); }); 
    $('#imp_sl_pts').on('input', calcImpFromPts);
    $('#imp_sl_price').on('input', calcImpFromPrice);

    // Auto-Remove Floating Notifications
    setTimeout(function() {
        $('.floating-alert').fadeOut('slow', function() {
            $(this).remove();
        });
    }, 4000); 

    // Loops
    setInterval(updateClock, 1000); updateClock();
    
    // Trade Data Update Loop (Uses Configured Interval)
    setInterval(updateData, REFRESH_INTERVAL); updateData();
});

function updateDisplayValues() {
    let mode = $('#mode_input').val(); 
    let s = settings.modes[mode]; if(!s) return;
    $('#qty_mult_disp').text(s.qty_mult); 
    $('#r_t1').text(s.ratios[0]); 
    $('#r_t2').text(s.ratios[1]); 
    $('#r_t3').text(s.ratios[2]); 
    if(typeof calcRisk === "function") calcRisk();
}

function switchTab(id) { 
    $('.dashboard-tab').hide(); $(`#${id}`).show(); 
    $('.nav-btn').removeClass('active'); $(event.target).addClass('active'); 
    if(id==='closed') loadClosedTrades(); 
    updateDisplayValues(); 
    if(id === 'trade') $('.sticky-footer').show(); else $('.sticky-footer').hide();
}

function setMode(el, mode) { 
    $('#mode_input').val(mode); 
    $(el).parent().find('.btn').removeClass('active'); 
    $(el).addClass('active'); 
    updateDisplayValues(); 
    loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'); 
}

function panicExit() {
    if(confirm("⚠️ URGENT: Are you sure you want to CLOSE ALL POSITIONS (Live & Paper) immediately?")) {
        $.post('/api/panic_exit', function(res) {
            if(res.status === 'success') {
                alert("🚨 Panic Protocol Initiated: All orders cancelled and positions squaring off.");
                location.reload();
            } else {
                alert("Error: " + res.message);
            }
        });
    }
}

// --- IMPORT TRADE LOGIC ---

// Helper for Quantity +/- Buttons
function adjImpQty(dir) {
    let q = $('#imp_qty');
    let v = parseInt(q.val()) || 0;
    // Attempt to use global curLotSize from trade.js, default to 1 if missing
    let step = (typeof curLotSize !== 'undefined' && curLotSize > 0) ? curLotSize : 1;
    let n = v + (dir * step);
    if(n < step) n = step;
    q.val(n);
}

// New Helpers for Import SL Calculation
function calcImpFromPts() {
    let entry = parseFloat($('#imp_price').val()) || 0;
    let pts = parseFloat($('#imp_sl_pts').val()) || 0;
    if(entry > 0) {
        $('#imp_sl_price').val((entry - pts).toFixed(2));
        calculateImportTargets(entry, pts);
    }
}
function calcImpFromPrice() {
    let entry = parseFloat($('#imp_price').val()) || 0;
    let price = parseFloat($('#imp_sl_price').val()) || 0;
    if(entry > 0) {
        let pts = entry - price;
        $('#imp_sl_pts').val(pts.toFixed(2));
        calculateImportTargets(entry, pts);
    }
}
function calculateImportTargets(entry, pts) {
    if(!entry || !pts) return;
    let ratios = settings.modes.PAPER.ratios || [0.5, 1.0, 1.5];
    $('#imp_t1').val((entry + (pts * ratios[0])).toFixed(2));
    $('#imp_t2').val((entry + (pts * ratios[1])).toFixed(2));
    $('#imp_t3').val((entry + (pts * ratios[2])).toFixed(2));
    
    // Visual update for full exit checkboxes
    ['t1', 't2', 't3'].forEach(k => {
        if ($(`#imp_${k}_full`).is(':checked')) $(`#imp_${k}_lots`).val(1000);
    });
}

function calculateImportRisk() {
    // Triggered by Button: Use existing values to refresh targets, or default if empty
    let entry = parseFloat($('#imp_price').val()) || 0;
    let pts = parseFloat($('#imp_sl_pts').val()) || 0;
    let price = parseFloat($('#imp_sl_price').val()) || 0;
    
    if(entry === 0) return;

    if (pts > 0) {
        // Recalc price based on points
        $('#imp_sl_price').val((entry - pts).toFixed(2));
    } else if (price > 0) {
        // Recalc points based on price
        pts = entry - price;
        $('#imp_sl_pts').val(pts.toFixed(2));
    } else {
        // Default fallbacks
        pts = 20;
        $('#imp_sl_pts').val(pts.toFixed(2));
        $('#imp_sl_price').val((entry - pts).toFixed(2));
    }
    calculateImportTargets(entry, pts);
}

function submitImport() {
    let d = {
        symbol: $('#imp_sym').val(),
        expiry: $('#imp_exp').val(),
        strike: $('#imp_str').val(),
        type: $('input[name="imp_type"]:checked').val(),
        entry_time: $('#imp_time').val(),
        qty: parseInt($('#imp_qty').val()),
        price: parseFloat($('#imp_price').val()),
        sl: parseFloat($('#imp_sl_price').val()), // Send SL Price to Backend
        
        // New Settings
        trailing_sl: parseFloat($('#imp_trail_sl').val()) || 0,
        sl_to_entry: parseInt($('#imp_trail_limit').val()) || 0,
        exit_multiplier: parseInt($('#imp_exit_mult').val()) || 1,
        
        targets: [
            parseFloat($('#imp_t1').val())||0,
            parseFloat($('#imp_t2').val())||0,
            parseFloat($('#imp_t3').val())||0
        ],
        
        target_controls: [
            { 
                enabled: $('#imp_t1_active').is(':checked'), 
                lots: $('#imp_t1_full').is(':checked') ? 1000 : (parseInt($('#imp_t1_lots').val()) || 0),
                trail_to_entry: $('#imp_t1_cost').is(':checked')
            },
            { 
                enabled: $('#imp_t2_active').is(':checked'), 
                lots: $('#imp_t2_full').is(':checked') ? 1000 : (parseInt($('#imp_t2_lots').val()) || 0),
                trail_to_entry: $('#imp_t2_cost').is(':checked')
            },
            { 
                enabled: $('#imp_t3_active').is(':checked'), 
                lots: $('#imp_t3_full').is(':checked') ? 1000 : (parseInt($('#imp_t3_lots').val()) || 0),
                trail_to_entry: $('#imp_t3_cost').is(':checked')
            }
        ]
    };
    
    if(!d.symbol || !d.entry_time || !d.price) { alert("Please fill all fields"); return; }
    
    $.ajax({
        type: "POST", url: '/api/import_trade', 
        data: JSON.stringify(d), contentType: "application/json",
        success: function(r) {
            if(r.status === 'success') {
                alert(r.message);
                $('#importModal').modal('hide');
                updateData(); 
            } else {
                alert("Error: " + r.message);
            }
        }
    });
}

function renderWatchlist() {
    if (typeof settings === 'undefined' || !settings.watchlist) return;
    let wl = settings.watchlist || [];
    let opts = '<option value="">📺 Select</option>';
    wl.forEach(w => { opts += `<option value="${w}">${w}</option>`; });
    $('#trade_watch').html(opts);
    $('#imp_watch').html(opts); 
}
