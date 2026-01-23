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
        vertLines: { color: '#404040' }, 
        horzLines: { color: '#404040' } 
    },
    // Set initial size based on container
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

// Add Candlestick Series
const candlestickSeries = chart.addCandlestickSeries({
    upColor: '#26a69a', 
    downColor: '#ef5350', 
    borderVisible: false, 
    wickUpColor: '#26a69a', 
    wickDownColor: '#ef5350'
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
        console.log(`Fetching data for: ${symbol}`);
        
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
        alert("Failed to load chart data. Check console for details.");
    }
}

// ---------------------------------------------------------------------------
// 3. RESPONSIVE RESIZE HANDLING
// ---------------------------------------------------------------------------
window.addEventListener('resize', () => {
    chart.applyOptions({ 
        width: chartContainer.clientWidth,
        height: chartContainer.clientHeight 
    });
});

// ---------------------------------------------------------------------------
// 4. SYMBOL SEARCH AUTO-COMPLETE LOGIC
// ---------------------------------------------------------------------------
const symbolInput = document.getElementById('chart_symbol');
const suggestionBox = document.getElementById('symbol-suggestions');
let debounceTimer;

symbolInput.addEventListener('input', function() {
    const query = this.value;
    
    // Clear any pending search to avoid flooding the server
    clearTimeout(debounceTimer);
    
    // Hide dropdown if query is too short
    if (query.length < 2) {
        suggestionBox.style.display = 'none';
        return;
    }

    // Debounce: Wait 300ms after user stops typing before searching
    debounceTimer = setTimeout(async () => {
        try {
            const res = await fetch(`/api/search_symbols?q=${encodeURIComponent(query)}`);
            const results = await res.json();
            
            // Clear previous results
            suggestionBox.innerHTML = '';
            
            if (results.length > 0) {
                suggestionBox.style.display = 'block';
                
                results.forEach(item => {
                    // Create suggestion item
                    const div = document.createElement('button');
                    div.className = 'list-group-item list-group-item-action list-group-item-dark p-2 text-start';
                    div.style.fontSize = '0.85rem';
                    div.style.cursor = 'pointer';
                    
                    // Format Label: "SYMBOL (EXCHANGE)"
                    div.innerHTML = `<strong>${item.label.split(' ')[0]}</strong> <small class="text-muted">${item.label.split(' ')[1] || ''}</small>`;
                    
                    // Handle Click Selection
                    div.onclick = () => {
                        symbolInput.value = item.value; // Set input to "EXCHANGE:SYMBOL"
                        suggestionBox.style.display = 'none'; // Hide dropdown
                        loadChartData(); // Immediately load chart
                    };
                    
                    suggestionBox.appendChild(div);
                });
            } else {
                suggestionBox.style.display = 'none';
            }
        } catch (e) {
            console.error("Search API failed", e);
        }
    }, 300);
});

// Close dropdown when clicking outside the input or dropdown
document.addEventListener('click', function(e) {
    if (e.target !== symbolInput && e.target !== suggestionBox) {
        suggestionBox.style.display = 'none';
    }
});

// ---------------------------------------------------------------------------
// 5. INITIAL LOAD
// ---------------------------------------------------------------------------
// Load the default symbol (NIFTY 50) when page opens
window.onload = loadChartData;
