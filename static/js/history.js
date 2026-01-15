// Global variable
var allClosedTrades = [];

$(document).ready(function() {
    // 1. Set Date to Today but DO NOT FILTER STRICTLY yet
    var d = new Date();
    var day = ("0" + d.getDate()).slice(-2);
    var month = ("0" + (d.getMonth() + 1)).slice(-2);
    var today = d.getFullYear() + "-" + month + "-" + day;
    
    var dateInput = document.getElementById('hist_date');
    if (dateInput) {
        dateInput.value = today;
    }

    // 2. Load History
    loadClosedTrades();
});

// --- SAFE HELPERS ---
function safeFixed(val, d=2) {
    if (val === undefined || val === null || isNaN(val)) return (0).toFixed(d);
    return parseFloat(val).toFixed(d);
}

function getSafeBadge(mode) {
    if(mode === 'LIVE') return '<span class="badge bg-danger">LIVE</span>';
    return '<span class="badge bg-secondary">PAPER</span>';
}

function loadClosedTrades() {
    // Get filter values
    let filterDate = $('#hist_date').val(); 
    let filterType = $('#hist_filter').val();
    
    $('#hist-container').html(`
        <div class="text-center mt-5 text-muted">
            <div class="spinner-border text-primary" role="status"></div>
            <p class="mt-2 small">Loading history...</p>
        </div>
    `);

    $.get('/api/closed_trades', function(trades) {
        allClosedTrades = trades || []; 
        let html = ''; 
        let dayTotal = 0, totalWins = 0, totalLosses = 0, totalPotential = 0, totalCapital = 0;

        // Filter Logic
        let filtered = allClosedTrades.filter(function(t) {
            // If date is selected, check match. If empty, show all.
            if (filterDate && t.exit_time && !t.exit_time.startsWith(filterDate)) return false;
            
            let mode = t.mode || 'PAPER';
            if (filterType !== 'ALL' && mode !== filterType) return false;
            return true;
        });

        if(filtered.length === 0) {
            html = '<div class="text-center p-4 text-muted bg-light border rounded mt-2">No History for this Date/Filter</div>';
        } else {
            filtered.forEach(function(t) {
                // Safe Data Access
                let pnl = t.pnl || 0;
                let qty = t.quantity || 0;
                let entry = t.entry_price || 0;
                let exit = t.exit_price || 0;
                let ltp = t.current_ltp || exit;
                let sl = t.sl || 0;
                let targets = t.targets || [0,0,0];
                let mode = t.mode || 'PAPER';

                dayTotal += pnl; 
                if(pnl > 0) totalWins += pnl; else totalLosses += pnl;
                totalCapital += (entry * qty);

                let color = pnl >= 0 ? 'text-success' : 'text-danger';
                let badge = getSafeBadge(mode);
                
                // Potential
                let potHtml = '';
                let potTag = ''; 
                let mh = t.made_high || entry;
                if(mh < exit) mh = exit;
                let pot = (mh - entry) * qty;

                if (t.status !== 'SL_HIT' || (t.targets_hit_indices && t.targets_hit_indices.length > 0)) {
                    if(pot > 0) {
                        totalPotential += pot;
                        if (targets.length >= 3) {
                            let bStyle = 'badge bg-white text-success border border-success';
                            if (mh >= targets[2]) potTag = `<span class="${bStyle}" style="font-size:0.65rem;">Pot. T3</span>`;
                            else if (mh >= targets[1]) potTag = `<span class="${bStyle}" style="font-size:0.65rem;">Pot. T2</span>`;
                            else if (mh >= targets[0]) potTag = `<span class="${bStyle}" style="font-size:0.65rem;">Pot. T1</span>`;
                        }
                        potHtml = `<div class="mt-2 p-1 rounded bg-light border border-warning border-opacity-25 d-flex justify-content-between align-items-center" style="font-size:0.75rem;">
                            <span class="text-muted">High: <b>${safeFixed(mh)}</b></span>
                            <span class="text-success fw-bold">Max Pot: ₹${safeFixed(pot,0)}</span>
                        </div>`;
                    }
                }

                let statusTag = `<span class="badge bg-secondary" style="font-size:0.65rem;">${t.status||'CLOSED'}</span>`;
                if(t.status === 'SL_HIT') statusTag = '<span class="badge bg-danger" style="font-size:0.65rem;">SL Hit</span>';
                else if((t.status||'').includes('TARGET')) statusTag = '<span class="badge bg-success" style="font-size:0.65rem;">Target Hit</span>';

                let timeStr = t.entry_time ? t.entry_time.slice(11, 16) : '--:--';
                
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
                        <hr class="my-1 opacity-25">
                        <div class="row g-0 text-center mt-2" style="font-size:0.75rem;">
                            <div class="col-3 border-end"> <div class="text-muted small">Qty</div> <div class="fw-bold">${qty}</div> </div>
                            <div class="col-3 border-end"> <div class="text-muted small">Entry</div> <div class="fw-bold">${safeFixed(entry)}</div> </div>
                            <div class="col-3 border-end"> <div class="text-muted small">Exit</div> <div class="fw-bold">${safeFixed(exit)}</div> </div>
                            <div class="col-3"> <div class="text-muted small">Fund</div> <div class="fw-bold">₹${safeFixed(entry*qty/1000, 1)}k</div> </div>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mt-2 px-1 bg-light rounded py-1" style="font-size:0.75rem;">
                            <span class="text-muted">Time: <b>${timeStr}</b></span>
                        </div>
                        ${potHtml}
                        <div class="sim-result-container"></div>
                        <div class="d-flex justify-content-end gap-2 mt-2 pt-1 border-top border-light">
                            <button class="btn btn-sm btn-outline-danger py-0 px-2" style="font-size:0.75rem;" onclick="deleteTrade('${t.id}')">🗑️</button>
                            <button class="btn btn-sm btn-light border text-muted py-0 px-2" style="font-size:0.75rem;" onclick="editSim('${t.id}')">✏️</button>
                        </div>
                    </div>
                </div>`;
            });
        }
        $('#hist-container').html(html);
        
        // Update Stats
        $('#day_pnl').text("₹ " + safeFixed(dayTotal));
        $('#day_pnl').removeClass('bg-success bg-danger').addClass(dayTotal >= 0 ? 'bg-success' : 'bg-danger');
        $('#total_wins').text("Wins: ₹ " + safeFixed(totalWins));
        $('#total_losses').text("Loss: ₹ " + safeFixed(totalLosses));
        $('#total_potential').text("Max Pot: ₹ " + safeFixed(totalPotential));
        $('#total_cap_hist').text("Funds: ₹ " + safeFixed(totalCapital/100000, 2) + " L");

        addSimButton();

    }).fail(function() {
        $('#hist-container').html('<div class="text-danger text-center mt-4">Failed to load history (API Error).</div>');
    });
}

function deleteTrade(id) { 
    if(confirm("Delete trade?")) $.post('/api/delete_trade/' + id, function(r) { if(r.status === 'success') loadClosedTrades(); }); 
}

function editSim(id) {
    let t = allClosedTrades.find(x => x.id == id); if(!t) return;
    $('.dashboard-tab').hide(); $('#history').show(); $('.nav-btn').removeClass('active'); $('.nav-btn').last().addClass('active');
    if(t.raw_params) {
        // Basic load attempt
        $('#h_sym').val(t.raw_params.symbol); $('#h_qty').val(t.quantity);
        alert("Parameters loaded into Simulator tab.");
    }
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
    let sl_pts = parseFloat($('#sim_sl').val()) || 0;
    let mult = parseInt($('#sim_mult').val()) || 1;
    let r1 = parseFloat($('#sim_r1').val()) || 0.5;
    let r2 = parseFloat($('#sim_r2').val()) || 1.0;
    let r3 = parseFloat($('#sim_r3').val()) || 1.5;

    let filterDate = $('#hist_date').val(); 
    let filterType = $('#hist_filter').val();

    for (let t of trades) {
        if (filterDate && t.exit_time && !t.exit_time.startsWith(filterDate)) continue;
        if (filterType !== 'ALL' && (t.mode||'PAPER') !== filterType) continue;

        let entry = t.entry_price || 0;
        let payload = {
            trade_id: t.id,
            sl_points: sl_pts,
            exit_multiplier: mult,
            targets: [entry + (sl_pts * r1), entry + (sl_pts * r2), entry + (sl_pts * r3)],
            target_controls: [{enabled:true,lots:0},{enabled:true,lots:0},{enabled:true,lots:1000}],
            trailing_sl: 0, sl_to_entry: 0
        };

        try {
            let resContainer = $(`#hist-card-${t.id} .sim-result-container`);
            resContainer.html('<div class="small text-info">⏳ ...</div>');
            let res = await $.ajax({type: "POST", url: '/api/simulate_trade', data: JSON.stringify(payload), contentType: "application/json"});
            
            if(res.status === 'success') {
                let diff = res.pnl - (t.pnl||0);
                resContainer.html(`<div class="mt-1 p-1 bg-white border border-info rounded small">
                    <span class="text-info fw-bold">What-If: ₹${safeFixed(res.pnl)}</span>
                    <span class="${diff>=0?'text-success':'text-danger'}">(${diff>=0?'+':''}${safeFixed(diff)})</span>
                    <br><span class="text-muted">${res.final_status} @ ${safeFixed(res.exit_price)}</span>
                </div>`);
            } else {
                resContainer.html(`<div class="text-danger small">Err: ${res.message}</div>`);
            }
        } catch(e) { console.error(e); }
    }
}
