// --- GLOBAL COUNTERS FOR 1ST TRADE LOGIC ---
var g_activeTrades = 0;
var g_closedTrades = 0;

$(document).ready(function() {
    // --- CONFIGURATION ---
    const REFRESH_INTERVAL = 500; 
    // ---------------------

    renderWatchlist();
    loadSettings();
    
    // Date Logic
    let now = new Date(); 
    const offset = now.getTimezoneOffset(); 
    let localDate = new Date(now.getTime() - (offset*60*1000));
    
    $('#hist_date').val(localDate.toISOString().slice(0,10)); 
    $('#imp_time').val(localDate.toISOString().slice(0,16)); 
    
    // Global Bindings
    $('#hist_date, #hist_filter').change(loadClosedTrades);
    $('#active_filter').change(updateData);
    
    $('input[name="type"]').change(function() {
        let s = $('#sym').val();
        if(s) loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts');
    });
    
    $('#sl_pts, #qty, #lim_pr, #ord').on('input change', calcRisk);
    
    bindSearch('#sym', '#sym_list'); 
    bindSearch('#imp_sym', '#sym_list'); 

    $('#sym').change(() => loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'));
    $('#exp').change(() => fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str'));
    $('#ord').change(function() { if($(this).val() === 'LIMIT') $('#lim_box').show(); else $('#lim_box').hide(); });
    $('#str').change(fetchLTP);

    $('#imp_sym').change(() => loadDetails('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_qty', '#imp_sl_pts')); 
    $('#imp_exp').change(() => fillChain('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_str'));
    $('#imp_str').change(fetchLTP);
    $('input[name="imp_type"]').change(() => loadDetails('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_qty', '#imp_sl_pts'));
    
    $('#imp_price').on('input', function() { calcImpFromPts(); }); 
    $('#imp_sl_pts').on('input', calcImpFromPts);
    $('#imp_sl_price').on('input', calcImpFromPrice);

    setTimeout(function() { $('.floating-alert').fadeOut('slow', function() { $(this).remove(); }); }, 4000); 

    setInterval(updateClock, 1000); updateClock();
    
    // START UPDATES
    setInterval(updateData, REFRESH_INTERVAL); updateData();
    loadClosedTrades(); // Initial Load
});

// --- CRITICAL TRADE LOGIC (1st Trade Enforcement) ---
function checkCriticalTradeLogic() {
    // Ensure settings are loaded and the feature is enabled
    if (typeof settings === 'undefined' || !settings || !settings.first_trade_critical) return;

    // Calculate total trades for the day
    let total = g_activeTrades + g_closedTrades;
    
    // If it is the FIRST trade (Total = 0)
    if (total === 0) {
        // 1. FORCE MODE TO SHADOW
        let currMode = $('#mode_input').val();
        if(currMode !== 'SHADOW') {
            // Programmatically click the SHADOW button to switch mode and update UI
            let btn = $(`.btn[onclick*="setMode"][onclick*="'SHADOW'"]`);
            if(btn.length) {
                // console.log("1st Trade Critical: Forcing SHADOW Mode");
                btn.click();
            }
        }

        // 2. FORCE BROADCAST TO FREE ONLY
        if($('#chk_free').length) {
            let isFree = $('#chk_free').is(':checked');
            let isVip = $('#chk_vip').is(':checked');
            let isZ2h = $('#chk_z2h').is(':checked');

            // Apply override if current state matches "Normal" defaults (VIP/Z2H enabled or Free disabled)
            if (!isFree || isVip || isZ2h) {
                // console.log("1st Trade Critical: Forcing FREE Channel Only");
                $('#chk_free').prop('checked', true);
                $('#chk_vip').prop('checked', false);
                $('#chk_z2h').prop('checked', false);
            }
        }
    }
}

// Update Data (Active Trades) -> Updates g_activeTrades & LTP
function updateData() {
    // [FIX] Send the current symbol to backend to get the correct LTP
    let currentSym = $('#sym').val(); 
    if(!currentSym) currentSym = $('#imp_sym').val(); // fallback to import field if active

    $.get('/update_data', { symbol: currentSym }, function(res) {
        if(res.redirect) window.location.href = res.redirect;
        
        // Update Headers (LTP)
        let ltpVal = res.ltp || 0;
        $('#inst_ltp').text("LTP: " + ltpVal);
        
        // Also update the badge inside the Import Modal if open
        if($('#importModal').hasClass('show')) {
             $('#imp_ltp').text("LTP: " + ltpVal);
        }
        
        // Count Active Trades
        let trades = res.trades || [];
        let validTrades = trades.filter(t => t.id); // Filter out potential nulls
        g_activeTrades = validTrades.length;
        
        // Check 1st Trade Logic after updating count
        checkCriticalTradeLogic();

        let tbody = $('#active_table_body');
        tbody.empty();
        let total_pnl = 0;
        
        let filter = $('#active_filter').val();
        
        trades.forEach(t => {
            if(filter !== 'ALL' && t.mode !== filter) return;
            
            let pnl = (t.current_price - t.entry_price) * t.quantity;
            total_pnl += pnl;
            
            let cls = pnl >= 0 ? 'pnl-green' : 'pnl-red';
            let row = `
                <tr>
                    <td><span class="badge bg-${t.mode==='LIVE'?'danger':(t.mode==='SHADOW'?'secondary':'warning')}">${t.mode}</span></td>
                    <td class="fw-bold">${t.symbol}</td>
                    <td>${t.quantity}</td>
                    <td>${t.entry_price}</td>
                    <td>${t.current_price}</td>
                    <td class="${cls} fw-bold">${pnl.toFixed(2)}</td>
                    <td>
                        <button class="btn btn-sm btn-info py-0" onclick="editTrade('${t.id}')">✏️</button>
                        <button class="btn btn-sm btn-warning py-0" onclick="exitTrade('${t.id}')">🚪</button>
                    </td>
                </tr>
            `;
            tbody.append(row);
        });
        
        $('#total_pnl').text('₹ ' + total_pnl.toFixed(2)).removeClass('pnl-green pnl-red').addClass(total_pnl >= 0 ? 'pnl-green' : 'pnl-red');
    });
}

// Load Closed Trades -> Updates g_closedTrades
function loadClosedTrades() {
    let date = $('#hist_date').val();
    let filter = $('#hist_filter').val();
    
    $.get('/history', { date: date }, function(res) {
        let trades = res.trades || [];
        
        // Count Closed Trades (Only if date displayed is TODAY)
        let nowStr = new Date().toISOString().slice(0,10);
        if (date === nowStr) {
            g_closedTrades = trades.length;
            // Re-check logic (e.g., if a trade was deleted, count drops to 0, logic re-engages)
            checkCriticalTradeLogic();
        }

        let tbody = $('#closed_table_body');
        tbody.empty();
        let day_pnl = 0;
        
        trades.forEach(t => {
            if(filter !== 'ALL' && t.mode !== filter) return;
            day_pnl += t.pnl;
            let cls = t.pnl >= 0 ? 'pnl-green' : 'pnl-red';
            let row = `
                <tr>
                    <td>${t.exit_time.split(' ')[1]}</td>
                    <td><span class="badge bg-${t.mode==='LIVE'?'danger':(t.mode==='SHADOW'?'secondary':'warning')}">${t.mode}</span></td>
                    <td class="fw-bold">${t.symbol}</td>
                    <td class="${cls} fw-bold">${t.pnl.toFixed(2)}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-secondary py-0" onclick='showLogs(${JSON.stringify(t.logs)})'>📄</button>
                        <button class="btn btn-sm btn-outline-primary py-0" onclick="importTrade('${t.id}')">♻️</button>
                    </td>
                </tr>
            `;
            tbody.append(row);
        });
        $('#day_pnl').text('₹ ' + day_pnl.toFixed(2)).removeClass('pnl-green pnl-red').addClass(day_pnl >= 0 ? 'pnl-green' : 'pnl-red');
    });
}

function updateDisplayValues() {
    let mode = $('#mode_input').val(); 
    if(!settings || !settings.modes) return; // Safety check
    
    let s = settings.modes[mode]; 
    if(!s) return;
    
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
    
    // Update visual state of buttons
    $('.btn[onclick*="setMode"]').removeClass('active');
    
    // Handle both direct click (el exists) and programmatic calls (el null)
    if (el) {
        $(el).addClass('active');
    } else {
        $(`.btn[onclick*="setMode"][onclick*="'${mode}'"]`).addClass('active');
    }
    
    updateDisplayValues(); 
    if(typeof loadDetails === 'function') loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'); 
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

// --- IMPORT & CALCULATOR FUNCTIONS ---
function adjImpQty(dir) { let q = $('#imp_qty'); let v = parseInt(q.val()) || 0; let step = (typeof curLotSize !== 'undefined' && curLotSize > 0) ? curLotSize : 1; let n = v + (dir * step); if(n < step) n = step; q.val(n); }
function calcImpFromPts() { let entry = parseFloat($('#imp_price').val()) || 0; let pts = parseFloat($('#imp_sl_pts').val()) || 0; if(entry > 0) { $('#imp_sl_price').val((entry - pts).toFixed(2)); calculateImportTargets(entry, pts); } }
function calcImpFromPrice() { let entry = parseFloat($('#imp_price').val()) || 0; let price = parseFloat($('#imp_sl_price').val()) || 0; if(entry > 0) { let pts = entry - price; $('#imp_sl_pts').val(pts.toFixed(2)); calculateImportTargets(entry, pts); } }
function calculateImportTargets(entry, pts) { if(!entry || !pts) return; let ratios = settings.modes.PAPER.ratios || [0.5, 1.0, 1.5]; $('#imp_t1').val((entry + (pts * ratios[0])).toFixed(2)); $('#imp_t2').val((entry + (pts * ratios[1])).toFixed(2)); $('#imp_t3').val((entry + (pts * ratios[2])).toFixed(2)); ['t1', 't2', 't3'].forEach(k => { if ($(`#imp_${k}_full`).is(':checked')) $(`#imp_${k}_lots`).val(1000); }); }
function calculateImportRisk() { let entry = parseFloat($('#imp_price').val()) || 0; let pts = parseFloat($('#imp_sl_pts').val()) || 0; let price = parseFloat($('#imp_sl_price').val()) || 0; if(entry === 0) return; if (pts > 0) { $('#imp_sl_price').val((entry - pts).toFixed(2)); } else if (price > 0) { pts = entry - price; $('#imp_sl_pts').val(pts.toFixed(2)); } else { pts = 20; $('#imp_sl_pts').val(pts.toFixed(2)); $('#imp_sl_price').val((entry - pts).toFixed(2)); } calculateImportTargets(entry, pts); }
function submitImport() { let d = { symbol: $('#imp_sym').val(), expiry: $('#imp_exp').val(), strike: $('#imp_str').val(), type: $('input[name="imp_type"]:checked').val(), entry_time: $('#imp_time').val(), qty: parseInt($('#imp_qty').val()), price: parseFloat($('#imp_price').val()), sl: parseFloat($('#imp_sl_price').val()), trailing_sl: parseFloat($('#imp_trail_sl').val()) || 0, sl_to_entry: parseInt($('#imp_trail_limit').val()) || 0, exit_multiplier: parseInt($('#imp_exit_mult').val()) || 1, targets: [ parseFloat($('#imp_t1').val())||0, parseFloat($('#imp_t2').val())||0, parseFloat($('#imp_t3').val())||0 ], target_controls: [ { enabled: $('#imp_t1_active').is(':checked'), lots: $('#imp_t1_full').is(':checked') ? 1000 : (parseInt($('#imp_t1_lots').val()) || 0), trail_to_entry: $('#imp_t1_cost').is(':checked') }, { enabled: $('#imp_t2_active').is(':checked'), lots: $('#imp_t2_full').is(':checked') ? 1000 : (parseInt($('#imp_t2_lots').val()) || 0), trail_to_entry: $('#imp_t2_cost').is(':checked') }, { enabled: $('#imp_t3_active').is(':checked'), lots: $('#imp_t3_full').is(':checked') ? 1000 : (parseInt($('#imp_t3_lots').val()) || 0), trail_to_entry: $('#imp_t3_cost').is(':checked') } ] }; if(!d.symbol || !d.entry_time || !d.price) { alert("Please fill all fields"); return; } $.ajax({ type: "POST", url: '/api/import_trade', data: JSON.stringify(d), contentType: "application/json", success: function(r) { if(r.status === 'success') { alert(r.message); $('#importModal').modal('hide'); updateData(); } else { alert("Error: " + r.message); } } }); }
function renderWatchlist() { if (typeof settings === 'undefined' || !settings.watchlist) return; let wl = settings.watchlist || []; let opts = '<option value="">📺 Select</option>'; wl.forEach(w => { opts += `<option value="${w}">${w}</option>`; }); $('#trade_watch').html(opts); $('#imp_watch').html(opts); }
