function loadClosedTrades() {
    let filterDate = $('#hist_date').val(); let filterType = $('#hist_filter').val();
    $.get('/api/closed_trades', trades => {
        allClosedTrades = trades; let html = ''; 
        let dayTotal = 0;
        let totalWins = 0;
        let totalLosses = 0;
        let totalPotential = 0;
        let totalCapital = 0; 

        let filtered = trades.filter(t => t.exit_time && t.exit_time.startsWith(filterDate) && (filterType === 'ALL' || getTradeCategory(t) === filterType));
        if(filtered.length === 0) html = '<div class="text-center p-4 text-muted">No History for this Date/Filter</div>';
        else {
            filtered.forEach(t => {
                dayTotal += t.pnl; 
                if(t.pnl > 0) totalWins += t.pnl;
                else totalLosses += t.pnl;
                
                let invested = t.entry_price * t.quantity; 
                totalCapital += invested;

                let color = t.pnl >= 0 ? 'text-success' : 'text-danger';
                let cat = getTradeCategory(t); 
                let badge = getMarkBadge(cat);
                
                // --- Potential Profit Logic ---
                let potHtml = '';
                let potTag = ''; 
                let isPureSL = (t.status === 'SL_HIT' && (!t.targets_hit_indices || t.targets_hit_indices.length === 0));

                if (!isPureSL) {
                    let mh = t.made_high || t.entry_price;
                    if(mh < t.exit_price) mh = t.exit_price; 
                    let pot = (mh - t.entry_price) * t.quantity;
                    
                    if(pot > 0) {
                        totalPotential += pot; 
                        
                        if (t.targets && t.targets.length >= 3) {
                            let badgeStyle = 'badge bg-white text-success border border-success';
                            if (mh >= t.targets[2]) potTag = `<span class="${badgeStyle}" style="font-size:0.65rem;">Pot. T3</span>`;
                            else if (mh >= t.targets[1]) potTag = `<span class="${badgeStyle}" style="font-size:0.65rem;">Pot. T2</span>`;
                            else if (mh >= t.targets[0]) potTag = `<span class="${badgeStyle}" style="font-size:0.65rem;">Pot. T1</span>`;
                        }
                        
                        potHtml = `
                        <div class="mt-2 p-1 rounded bg-light border border-warning border-opacity-25 d-flex justify-content-between align-items-center" style="font-size:0.75rem;">
                            <span class="text-muted">High: <b>${mh.toFixed(2)}</b></span>
                            <span class="text-success fw-bold">Max Potential: ₹${pot.toFixed(0)}</span>
                        </div>`;
                    }
                }

                // --- Status Tags ---
                let statusTag = '';
                let rawStatus = t.status || '';
                
                if (rawStatus === 'SL_HIT') {
                    statusTag = '<span class="badge bg-danger" style="font-size:0.65rem;">Stop-Loss</span>';
                } 
                else if (rawStatus.includes('TARGET')) {
                     let maxHit = -1;
                     if (t.targets_hit_indices && t.targets_hit_indices.length > 0) {
                         maxHit = Math.max(...t.targets_hit_indices);
                     } else {
                         if(rawStatus.includes('1')) maxHit = 0;
                         if(rawStatus.includes('2')) maxHit = 1;
                         if(rawStatus.includes('3')) maxHit = 2;
                     }

                     if (maxHit === 0) statusTag = '<span class="badge bg-success" style="font-size:0.65rem;">T1 Hit</span>';
                     else if (maxHit === 1) statusTag = '<span class="badge bg-success" style="font-size:0.65rem;">T2 Hit</span>';
                     else statusTag = '<span class="badge bg-success" style="font-size:0.65rem;">T3 Hit</span>'; 
                } 
                else if (rawStatus === 'COST_EXIT') {
                    statusTag = '<span class="badge bg-warning text-dark" style="font-size:0.65rem;">Cost Exit</span>';
                } 
                else {
                    statusTag = `<span class="badge bg-secondary" style="font-size:0.65rem;">${rawStatus}</span>`;
                }

                // --- NEW TIME & ACTIVATION DURATION LOGIC ---
                
                // 1. Added Time (From DB)
                let addedTimeStr = t.entry_time ? t.entry_time.slice(11, 16) : '--:--';
                let addedDateObj = t.entry_time ? new Date(t.entry_time) : null;
                
                // 2. Active Time (Parse Logs)
                let activeTimeStr = '--:--';
                let waitDuration = '';
                
                if (t.logs && t.logs.length > 0) {
                    let activationLog = t.logs.find(l => l.includes('Order ACTIVATED'));
                    
                    if (activationLog) {
                        // Extract [YYYY-MM-DD HH:MM:SS]
                        let match = activationLog.match(/\[(.*?)\]/);
                        if (match && match[1]) {
                            activeTimeStr = match[1].slice(11, 16); // Extract HH:MM
                            
                            // Calculate Duration
                            let activeDateObj = new Date(match[1]);
                            if(addedDateObj && activeDateObj) {
                                let diff = activeDateObj - addedDateObj; // in ms
                                if(diff > 0) {
                                    let totalSecs = Math.floor(diff / 1000);
                                    let m = Math.floor(totalSecs / 60);
                                    let s = totalSecs % 60;
                                    waitDuration = `<span class="text-muted ms-1" style="font-size:0.65rem;">(${m}m ${s}s)</span>`;
                                }
                            }
                        }
                    } else {
                        // Check if it was OPEN immediately (Market Order)
                        let firstLog = t.logs[0] || "";
                        if (firstLog.includes("Status: OPEN")) {
                            activeTimeStr = addedTimeStr;
                            waitDuration = `<span class="text-muted ms-1" style="font-size:0.65rem;">(Instant)</span>`;
                        }
                    }
                }

                // --- Actions ---
                let editBtn = (t.order_type === 'SIMULATION') ? `<button class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:0.75rem;" onclick="editSim('${t.id}')">✏️</button>` : '';
                let delBtn = `<button class="btn btn-sm btn-outline-danger py-0 px-2" style="font-size:0.75rem;" onclick="deleteTrade('${t.id}')">🗑️</button>`;
                
                // --- Mobile-First Card Design ---
                html += `
                <div class="card mb-2 shadow-sm border-0">
                    <div class="card-body p-2">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <div>
                                <span class="fw-bold text-dark h6 m-0">${t.symbol}</span>
                                <div class="mt-1 d-flex gap-1 align-items-center flex-wrap">
                                    ${badge} ${statusTag} ${potTag}
                                </div>
                            </div>
                            <div class="text-end">
                                <div class="fw-bold h6 m-0 ${color}">${t.pnl.toFixed(2)}</div>
                            </div>
                        </div>

                        <hr class="my-1 text-muted opacity-25">

                        <div class="row g-0 text-center mt-2" style="font-size:0.75rem;">
                            <div class="col-3 border-end">
                                <div class="text-muted small">Qty</div>
                                <div class="fw-bold text-dark">${t.quantity}</div>
                            </div>
                            <div class="col-3 border-end">
                                <div class="text-muted small">Entry</div>
                                <div class="fw-bold text-dark">${t.entry_price.toFixed(2)}</div>
                            </div>
                            <div class="col-3 border-end">
                                <div class="text-muted small">LTP</div>
                                <div class="fw-bold text-dark">${t.current_ltp ? t.current_ltp.toFixed(2) : t.exit_price.toFixed(2)}</div>
                            </div>
                            <div class="col-3">
                                <div class="text-muted small">Fund</div>
                                <div class="fw-bold text-dark">₹${(invested/1000).toFixed(1)}k</div>
                            </div>
                        </div>

                        <div class="d-flex justify-content-between align-items-center mt-2 px-1 bg-light rounded py-1" style="font-size:0.75rem;">
                            <span class="text-muted">Added: <b>${addedTimeStr}</b></span>
                            <div class="d-flex align-items-center">
                                <span class="text-primary">Active: <b>${activeTimeStr}</b></span>
                                ${waitDuration}
                            </div>
                        </div>

                        <div class="d-flex justify-content-between align-items-center mt-2 px-1" style="font-size:0.75rem;">
                             <span class="text-danger fw-bold">SL: ${t.sl.toFixed(1)}</span>
                             <span class="text-muted">T: ${t.targets[0].toFixed(0)} | ${t.targets[1].toFixed(0)} | ${t.targets[2].toFixed(0)}</span>
                        </div>

                        ${potHtml}

                        <div class="d-flex justify-content-end gap-2 mt-2 pt-1 border-top border-light">
                            ${editBtn}
                            ${delBtn}
                            <button class="btn btn-sm btn-light border text-muted py-0 px-2" style="font-size:0.75rem;" onclick="showLogs('${t.id}', 'closed')">📜 Logs</button>
                        </div>
                    </div>
                </div>`;
            });
        }
        $('#hist-container').html(html); 
        
        // Update Summary Badges
        $('#day_pnl').text("₹ " + dayTotal.toFixed(2));
        if(dayTotal >= 0) $('#day_pnl').removeClass('bg-danger').addClass('bg-success'); else $('#day_pnl').removeClass('bg-success').addClass('bg-danger');

        $('#total_wins').text("Wins: ₹ " + totalWins.toFixed(2));
        $('#total_losses').text("Loss: ₹ " + totalLosses.toFixed(2));
        $('#total_potential').text("Max Potential: ₹ " + totalPotential.toFixed(2));
        $('#total_cap_hist').text("Funds Used: ₹ " + (totalCapital/100000).toFixed(2) + " L");
    });
}

function deleteTrade(id) { 
    if(confirm("Delete trade?")) $.post('/api/delete_trade/' + id, r => { if(r.status === 'success') loadClosedTrades(); else alert('Failed to delete'); }); 
}

function editSim(id) {
    let t = allClosedTrades.find(x => x.id == id); if(!t) return;
    $('.dashboard-tab').hide(); $('#history').show(); $('.nav-btn').removeClass('active'); $('.nav-btn').last().addClass('active');
    if(t.raw_params) {
        $('#h_sym').val(t.raw_params.symbol); $('#h_entry').val(t.entry_price); $('#h_qty').val(t.quantity); $('#h_time').val(t.raw_params.time);
        $(`input[name="h_type"][value="${t.raw_params.type}"]`).prop('checked', true);
        loadDetails('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_qty', '#h_sl_pts');
        setTimeout(() => { $('#h_exp').val(t.raw_params.expiry).change(); setTimeout(() => { $('#h_str').val(t.raw_params.strike).change(); }, 500); }, 800);
    } else alert("Old trade format.");
}
