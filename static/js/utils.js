// Global Variables
let settings = { 
    exchanges: ['NSE', 'NFO', 'MCX', 'CDS', 'BSE', 'BFO'],
    watchlist: [],
    modes: {
        LIVE: {qty_mult: 1, ratios: [0.5, 1.0, 1.5], symbol_sl: {}},
        PAPER: {qty_mult: 1, ratios: [0.5, 1.0, 1.5], symbol_sl: {}}
    }
};

let curLotSize = 1;
let symLTP = {}; 
let activeTradesList = []; 
let allClosedTrades = [];
let curLTP = 0;

// Helper Functions
function normalizeSymbol(s) {
    if(!s) return "";
    s = s.toUpperCase().trim();
    if(s.includes('(')) s = s.split('(')[0].trim();
    if(s.includes(':')) s = s.split(':')[0].trim();
    
    if(['NIFTY', 'NIFTY 50', 'NIFTY50'].includes(s)) return 'NIFTY';
    if(['BANKNIFTY', 'NIFTY BANK', 'BANK NIFTY'].includes(s)) return 'BANKNIFTY';
    if(['FINNIFTY', 'NIFTY FIN SERVICE'].includes(s)) return 'FINNIFTY';
    if(['SENSEX', 'BSE SENSEX'].includes(s)) return 'SENSEX';
    return s;
}

function getTradeCategory(t) { 
    if (t.mode === 'LIVE') return 'LIVE'; 
    return 'PAPER'; 
}

function getMarkBadge(category) { 
    if (category === 'LIVE') return '<span class="badge bg-danger" style="font-size:0.7rem;">LIVE</span>'; 
    return '<span class="badge bg-warning text-dark" style="font-size:0.7rem;">PAPER</span>'; 
}

function updateClock() { 
    $('#live_clock').text(new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })); 
}

function showLogs(tradeId, type) {
    let trade = (type === 'active') ? activeTradesList.find(x => x.id == tradeId) : allClosedTrades.find(x => x.id == tradeId);
    if (trade && trade.logs) { 
        $('#logModalBody').html(trade.logs.map(l => `<div class="log-entry">${l}</div>`).join('')); 
        new bootstrap.Modal(document.getElementById('logModal')).show(); 
    } else {
        alert("No logs available.");
    }
}

function bindSearch(id, listId) { 
    $(id).on('input', function() { 
        if(this.value.length > 1) {
            $.get('/api/search?q='+this.value, d => { 
                $(listId).empty(); 
                d.forEach(s => $(listId).append(`<option value="${s}">`)); 
            }); 
        }
    }); 
}
