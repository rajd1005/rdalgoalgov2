// Global variable to store trades
var allClosedTrades = [];

// Initialize when document is ready
$(document).ready(function() {
    // Set Date Picker to Today
    var d = new Date();
    var day = ("0" + d.getDate()).slice(-2);
    var month = ("0" + (d.getMonth() + 1)).slice(-2);
    var today = d.getFullYear() + "-" + month + "-" + day;
    
    var dateInput = document.getElementById('hist_date');
    if (dateInput) dateInput.value = today;

    // Load Data
    loadClosedTrades();
});

// --- SAFE HELPER FUNCTIONS (Internal) ---
function getTradeCategorySafe(t) {
    if (t.mode === 'PAPER') return 'PAPER';
    if (t.mode === 'LIVE') return 'LIVE';
    return 'PAPER';
}

function getMarkBadgeSafe(cat) {
    if (cat === 'LIVE') return '<span class="badge bg-danger">LIVE</span>';
    return '<span class="badge bg-secondary">PAPER</span>';
}

function safeFixed(val, d=2) {
    if (val === undefined || val === null || isNaN(val)) return (0).toFixed(d);
    return parseFloat(val).toFixed(d);
}

// --- MAIN LOGIC ---
function loadClosedTrades() {
    let filterDate = $('#hist_date').val(); 
    let filterType = $('#hist_filter').val();
    
    // Show loading spinner
    $('#hist-container').html(`
        <div class="text-center mt-5 text-muted">
            <div class="spinner-border text-primary" role="status"></div>
            <p class="mt-2 small">Loading history...</p>
        </div>
    `);

    $.get('/api/closed_trades', function(trades) {
        allClosedTrades = trades || []; 
        let html = ''; 
        let dayTotal = 0;
        let totalWins = 0;
        let totalLosses = 0;
        let totalPotential = 0;
        let totalCapital = 0; 

        // Filter Logic
        let filtered = allClosedTrades.filter(function(t) {
            // Safety: Ensure exit_time exists
            if (!t.exit_time) return false;
            // Date Filter
            if (filterDate && !t.exit_time.startsWith(filterDate)) return false;
            // Type Filter
            let cat = getTradeCategorySafe(t);
            if (filterType !== 'ALL' && cat !== filterType) return false;
            return true;
        });

        if(filtered.length === 0) {
            html = '<div class="text-center p-4 text-muted bg-light border rounded mt-2">No History for this Date/Filter</div>';
        } else {
            filtered.forEach(function(t) {
                // Sanitize Data
                let pnl = t.pnl || 0;
                let qty = t.quantity || 0;
                let entry = t.entry_price || 0;
                let exit = t.exit_price || 0;
                let ltp = t.current_ltp || exit;
                let sl = t.sl || 0;
                let targets = t.targets || [0,0,0];

                dayTotal += pnl; 
                if(pnl > 0) totalWins += pnl;
                else totalLosses += pnl;
                
                let invested = entry * qty; 
                totalCapital += invested;

                let color = pnl >= 0 ? 'text-success' : 'text-danger';
                let cat = getTradeCategorySafe(t); 
                let badge = getMarkBadgeSafe(cat);
                
                // Potential Profit Logic
                let potHtml = '';
                let potTag = ''; 
                let isPureSL = (t.status === 'SL_HIT' && (!t.targets_hit_indices || t.targets_hit_indices.length === 0));

                if (!isPureSL) {
                    let mh = t.made_high || entry;
                    if(mh < exit) mh = exit; 
                    let pot = (mh - entry) * qty;
                    
                    if(pot > 0) {
                        totalPotential += pot; 
                        if (targets.length >= 3) {
                            let bStyle = 'badge bg-white text-success border border-success';
                            if (mh >= targets[2]) potTag = `<span class="${bStyle}" style="font-size:0.65rem;">Pot. T3</span>`;
                            else if (mh >= targets[1]) potTag = `<span class="${bStyle}" style="font-size:0.65rem;">Pot. T2</span>`;
                            else if (mh >= targets[0]) potTag = `<span class="${bStyle}" style="font-size:0.65rem;">Pot. T1</span>`;
                        }
                        
                        potHtml = `
                        <div class="mt-2 p-1 rounded bg-light border border-warning border-opacity-25 d-flex justify-content-between align-items-center" style="font-size:0.75rem;">
                            <span class="text-muted">High: <b>${safeFixed(mh)}</b></span>
                            <span class="text-success fw-bold">Max Potential: ₹${safeFixed(pot, 0)}</span>
                        </div>`;
                    }
                }

                // Status Tags
                let statusTag = '';
                let rawStatus = t.status || '';
                
                if (rawStatus === 'SL_HIT') statusTag = '<span class="badge bg-danger" style="font-size:0.65rem;">Stop-Loss</span>';
                else if (rawStatus.includes('TARGET')) statusTag = '<span class="badge bg-success" style="font-size:0.65rem;">Target Hit</span>';
                else if (rawStatus === 'COST_EXIT') statusTag = '<span class="badge bg-warning text-dark" style="font-size:0.65rem;">Cost Exit</span>';
                else statusTag = `<span class="badge bg-secondary" style="font-size:0.65rem;">${rawStatus}</span>`;

                // Time Logic
                let addedTimeStr = t.entry_time ? t.entry_time.slice(11, 16) : '--:--';
                let activeTimeStr = '--:--';
                
                if (t.logs && t.logs.length > 0) {
                    let activationLog = t.logs.find(l => l.includes('Order ACTIVATED'));
                    if (activationLog) {
                        let match = activationLog.match(/\[(.*?)\]/);
                        if (match && match[1]) activeTimeStr = match[1].slice(11, 16);
                    } else if (t.logs[0].includes("Status: OPEN")) {
                        activeTimeStr = addedTimeStr;
                    }
                }

                let editBtn = (t.order_type === 'SIMULATION') ? `<button class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;" onclick="editSim('${t.id}')">✏️</button>` : '';

                // Build HTML
                html += `
                <div class="card mb-2 shadow-sm border-0" id="hist-card-${t.id}">
                    <div class="card-body p-2">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <div>
                                <span class="fw-bold text-dark h6 m-0">${t.symbol}</span>
                                <div class="mt-1 d-flex gap-1 align-items-center flex-wrap">
                                    ${badge} ${statusTag} ${potTag}
                                </div>
                            </div>
                            <div class="text-end">
                                <div class="fw-bold h6 m-0 ${color}">${safeFixed(pnl)}</div>
                            </div>
                        </div>

                        <hr class="my-1 text-muted opacity-25">

                        <div class="row g-0 text-center mt-2" style="font-size:0.75rem;">
                            <div class="col-3 border-end">
                                <div class="text-muted small">Qty</div>
                                <div class="fw-bold text-dark">${qty}</div>
                            </div>
                            <div class="col-3 border-end">
                                <div class="text-muted small">Entry</div>
                                <div class="fw-bold text-dark">${safeFixed(entry)}</div>
                            </div>
                            <div class="col-3 border-end">
                                <div class="text-muted small">LTP</div>
                                <div class="fw-bold text-dark">${safeFixed(ltp)}</div>
                            </div>
                            <div class="col-3">
                                <div class="text-muted small">Fund</div>
                                <div class="fw-bold text-dark">₹${safeFixed(invested/1000, 1)}k</div>
                            </div>
                        </div>

                        <div class="d-flex justify-content-between align-items-center mt-2 px-1 bg-light rounded py-1" style="font-size:0.75rem;">
                            <span class="text-muted">Added: <b>${addedTimeStr}</b></span>
                            <span class="text-primary">Active: <b>${activeTimeStr}</b></span>
                        </div>

                        <div class="d-flex justify-content-between align-items-center mt-2 px-1" style="font-size:0.75rem;">
                             <span class="text-danger fw-bold">SL: ${safeFixed(sl)}</span>
                             <span class="text-muted">T: ${safeFixed(targets[0],0)} | ${safeFixed(targets[1],0)} | ${safeFixed(targets[2],0)}</span>
                        </div>

                        ${potHtml}
                        
                        <div class="sim-result-container"></div>

                        <div class="d-flex justify-content-end gap-2 mt-2 pt-1 border-top border-light">
                            ${editBtn}
                            <button class="btn btn-sm btn-outline-danger py-0 px-2" style="font-size:0.75rem;" onclick="deleteTrade('${t.id}')">🗑️</button>
                            <button class="btn btn-sm btn-light border text-muted py-0 px-2" style="font-size:0.75rem;" onclick="showLogs('${t.id}', 'closed')">📜 Logs</button>
                        </div>
                    </div>
                </div>`;
            });
        }
        $('#hist-container').html(html); 
        
        // Update Summary
        $('#day_pnl').text("₹ " + safeFixed(dayTotal));
        $('#day_pnl').removeClass('bg-success bg-danger').addClass(dayTotal >= 0 ? 'bg-success' : 'bg-danger');

        $('#total_wins').text("Wins: ₹ " + safeFixed(totalWins));
        $('#total_losses').text("Loss: ₹ " + safeFixed(totalLosses));
        $('#total_potential').text("Max Pot: ₹ " + safeFixed(totalPotential));
        $('#total_cap_hist').text("Funds: ₹ " + safeFixed(totalCapital/100000, 2) + " L");

        // Ensure Sim Button Exists
        addSimButton();

    }).fail(function() {
        $('#hist-container').html('<div class="text-danger text-center mt-4">Failed to load trade history. Check server logs.</div>');
    });
}

function deleteTrade(id) { 
    if(confirm("Delete trade?")) $.post('/api/delete_trade/' + id, function(r) { if(r.status === 'success') loadClosedTrades(); else alert('Failed to delete'); }); 
}

function editSim(id) {
    let t = allClosedTrades.find(x => x.id == id); if(!t) return;
    $('.dashboard-tab').hide(); $('#history').show(); $('.nav-btn').removeClass('active'); $('.nav-btn').last().addClass('active');
    if(t.raw_params) {
        $('#h_sym').val(t.raw_params.symbol); $('#h_entry').val(t.entry_price); $('#h_qty').val(t.quantity); $('#h_time').val(t.raw_params.time);
        $(`input[name="h_type"][value="${t.raw_params.type}"]`).prop('checked', true);
        // Assuming loadDetails exists in main.js, if not, this part might fail but won't block initial load
        if(typeof loadDetails === 'function') {
            loadDetails('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_qty', '#h_sl_pts');
            setTimeout(() => { $('#h_exp').val(t.raw_params.expiry).change(); setTimeout(() => { $('#h_str').val(t.raw_params.strike).change(); }, 500); }, 800);
        }
    } else alert("Old trade format or cannot edit.");
}

function addSimButton() {
    if($('#sim-btn').length === 0) {
        $('#closed .custom-card .d-flex.gap-1').append(
            `<button id="sim-btn" class="btn btn-sm btn-outline-info fw-bold py-0" style="font-size: 0.8rem; border-width: 2px;" data-bs-toggle="modal" data-bs-target="#simModal">🧪 What-If</button>`
        );
    }
}

async function runBatchSimulation() {
    $('#simModal').modal('hide');
    let trades = allClosedTrades; 
    
    // Get Settings
    let sl_pts = parseFloat($('#sim_sl').val()) || 0;
    let mult = parseInt($('#sim_mult').val()) || 1;
    let r1 = parseFloat($('#sim_r1').val()) || 0.5;
    let r2 = parseFloat($('#sim_r2').val()) || 1.0;
    let r3 = parseFloat($('#sim_r3').val()) || 1.5;
    let l1 = parseInt($('#sim_l1').val()) || 0;
    let l2 = parseInt($('#sim_l2').val()) || 0;
    let l3 = parseInt($('#sim_l3').val()) || 0;
    let c1 = $('#sim_c1').is(':checked');
    let c2 = $('#sim_c2').is(':checked');
    let c3 = $('#sim_c3').is(':checked');

    let filterDate = $('#hist_date').val(); 
    let filterType = $('#hist_filter').val();

    for (let t of trades) {
        // Apply Filters
        if (!t.exit_time || (filterDate && !t.exit_time.startsWith(filterDate))) continue;
        if (filterType !== 'ALL' && getTradeCategorySafe(t) !== filterType) continue;

        let entry = t.entry_price || 0;
        let t1_p = entry + (sl_pts * r1);
        let t2_p = entry + (sl_pts * r2);
        let t3_p = entry + (sl_pts * r3);

        let payload = {
            trade_id: t.id,
            sl_points: sl_pts,
            exit_multiplier: mult,
            targets: [t1_p, t2_p, t3_p],
            target_controls: [
                { enabled: true, lots: l1, trail_to_entry: c1 },
                { enabled: true, lots: l2, trail_to_entry: c2 },
                { enabled: true, lots: l3 > 0 ? l3 : 1000, trail_to_entry: c3 }
            ],
            trailing_sl: 0, 
            sl_to_entry: 0
        };

        try {
            let cardId = `#hist-card-${t.id}`;
            let resultContainer = $(cardId).find('.sim-result-container');
            resultContainer.html('<div class="mt-2 p-1 bg-light border border-info rounded text-center small text-info">⏳ Running What-If...</div>');

            let res = await $.ajax({
                type: "POST",
                url: '/api/simulate_trade',
                data: JSON.stringify(payload),
                contentType: "application/json"
            });

            if (res.status === 'success') {
                let oldPnl = t.pnl || 0;
                let diff = res.pnl - oldPnl;
                let color = diff >= 0 ? 'text-success' : 'text-danger';
                let sign = diff >= 0 ? '+' : '';
                
                let html = `
                <div class="mt-2 p-1 bg-white border border-info rounded" style="font-size:0.75rem;">
                    <div class="d-flex justify-content-between fw-bold">
                        <span class="text-info">What-If P&L:</span>
                        <span class="${res.pnl >= 0 ? 'text-success' : 'text-danger'}">₹ ${safeFixed(res.pnl)}</span>
                    </div>
                    <div class="d-flex justify-content-between text-muted mt-1">
                        <span>Diff: <b class="${color}">${sign}${safeFixed(diff)}</b></span>
                        <span>${res.final_status} @ ${safeFixed(res.exit_price)}</span>
                    </div>
                </div>`;
                resultContainer.html(html);
            } else {
                resultContainer.html(`<div class="mt-2 text-danger small">Error: ${res.message}</div>`);
            }
        } catch (e) {
            console.error(e);
        }
    }
}
