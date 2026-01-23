// static/js/chart_config.js

// ---------------------------------------------------------------------------
// 1. INITIALIZE CHART (TradingView Lightweight Charts)
// ---------------------------------------------------------------------------
const chartContainer = document.getElementById('chart-container');

const chartOptions = { 
    layout: { 
        textColor: '#d1d4dc', 
        background: { type: 'solid', color: '#1a1a1a' } 
    },
    grid: { 
        vertLines: { color: '#2b2b2b' }, // Darker grid lines
        horzLines: { color: '#2b2b2b' } 
    },
    width: chartContainer.clientWidth,
    height: chartContainer.clientHeight,
    timeScale: { 
        timeVisible: true, 
        secondsVisible: false,
        borderColor: '#485c7b',
    },
    rightPriceScale: {
        borderColor: '#485c7b',
    },
};

// Create the chart instance
const chart = LightweightCharts.createChart(chartContainer, chartOptions);

// Add Candlestick Series (TradingView Colors)
const candlestickSeries = chart.addCandlestickSeries({
    upColor: '#089981',      // TV Green
    downColor: '#f23645',    // TV Red
    borderVisible: false, 
    wickUpColor: '#089981', 
    wickDownColor: '#f23645'
});

// ---------------------------------------------------------------------------
// 2. DATA FETCHING & RENDERING
// ---------------------------------------------------------------------------
async function loadChartData() {
    const symbolInput = document.getElementById('chart_symbol');
    const symbol = symbolInput.value;
    
    if(!symbol) {
        alert("Please enter a symbol!");
        return;
    }

    try {
        // Fetch historical data from backend API
        const response = await fetch(`/api/history_data?symbol=${encodeURIComponent(symbol)}`);
        const data = await response.json();

        if (data.status === 'error') {
            alert(`Error: ${data.message}`);
            return;
        }

        if (!data.candles || data.candles.length === 0) {
            alert("No data found for this symbol.");
            return;
        }

        // Format data for Lightweight Charts (requires Unix timestamp in seconds)
        const chartData = data.candles.map(c => ({
            time: new Date(c.date).getTime() / 1000, 
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        }));

        // Update the chart
        candlestickSeries.setData(chartData);
        
        // Adjust the view to fit all data
        chart.timeScale().fitContent();
        
    } catch (error) {
        console.error("Chart Load Error:", error);
    }
}

// ---------------------------------------------------------------------------
// 3. RESPONSIVE RESIZE HANDLING (Using ResizeObserver)
// ---------------------------------------------------------------------------
const resizeObserver = new ResizeObserver(entries => {
    for (let entry of entries) {
        chart.applyOptions({ 
            width: entry.contentRect.width, 
            height: entry.contentRect.height 
        });
    }
});

resizeObserver.observe(chartContainer);

// ---------------------------------------------------------------------------
// 4. SYMBOL SEARCH AUTO-COMPLETE LOGIC (TradingView Style)
// ---------------------------------------------------------------------------
const symbolInput = document.getElementById('chart_symbol');
const suggestionBox = document.getElementById('symbol-suggestions');
let debounceTimer;

symbolInput.addEventListener('input', function() {
    const query = this.value;
    
    clearTimeout(debounceTimer);
    
    if (query.length < 2) {
        suggestionBox.style.display = 'none';
        return;
    }

    debounceTimer = setTimeout(async () => {
        try {
            const res = await fetch(`/api/search_symbols?q=${encodeURIComponent(query)}`);
            const results = await res.json();
            
            suggestionBox.innerHTML = '';
            
            if (results.length > 0) {
                suggestionBox.style.display = 'block';
                
                results.forEach(item => {
                    const btn = document.createElement('button');
                    btn.className = 'list-group-item list-group-item-action list-group-item-dark p-2';
                    btn.style.borderLeft = 'none';
                    btn.style.borderRight = 'none';
                    btn.style.cursor = 'pointer';

                    // TRADINGVIEW STYLE LAYOUT: Symbol (Left) | Description (Right) | Exchange (Badge)
                    // The backend now returns: {symbol, desc, exchange, value}
                    btn.innerHTML = `
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <span class="fw-bold text-white">${item.symbol}</span>
                                <small class="text-muted ms-2">${item.desc}</small>
                            </div>
                            <span class="badge bg-secondary" style="font-size: 0.7em;">${item.exchange}</span>
                        </div>
                    `;
                    
                    // Handle Click Selection
                    btn.onclick = () => {
                        symbolInput.value = item.value; // e.g. "NSE:RELIANCE"
                        suggestionBox.style.display = 'none';
                        loadChartData();
                    };
                    
                    suggestionBox.appendChild(btn);
                });
            } else {
                suggestionBox.style.display = 'none';
            }
        } catch (e) {
            console.error("Search API failed", e);
        }
    }, 300);
});

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (e.target !== symbolInput && e.target !== suggestionBox) {
        suggestionBox.style.display = 'none';
    }
});

// ---------------------------------------------------------------------------
// 5. INITIAL LOAD
// ---------------------------------------------------------------------------
window.onload = loadChartData;
