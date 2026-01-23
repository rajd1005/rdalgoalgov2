// static/js/chart_config.js

// 1. Initialize Chart
const chartOptions = { 
    layout: { textColor: '#d1d4dc', background: { type: 'solid', color: '#1a1a1a' } },
    grid: { vertLines: { color: '#404040' }, horzLines: { color: '#404040' } },
    width: document.getElementById('chart-container').clientWidth,
    height: document.getElementById('chart-container').clientHeight,
    timeScale: { timeVisible: true, secondsVisible: false }
};

const chart = LightweightCharts.createChart(document.getElementById('chart-container'), chartOptions);
const candlestickSeries = chart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
    wickUpColor: '#26a69a', wickDownColor: '#ef5350'
});

// 2. Function to Fetch Data
async function loadChartData() {
    const symbol = document.getElementById('chart_symbol').value;
    if(!symbol) return alert("Enter a symbol!");

    try {
        // Call the new API endpoint
        const response = await fetch(`/api/history_data?symbol=${encodeURIComponent(symbol)}`);
        const data = await response.json();

        if (data.status === 'error') {
            alert(data.message);
            return;
        }

        // Format data for Lightweight Charts
        const chartData = data.candles.map(c => ({
            time: new Date(c.date).getTime() / 1000, // Convert to Unix Timestamp
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        }));

        candlestickSeries.setData(chartData);
        chart.timeScale().fitContent();
        
    } catch (error) {
        console.error("Chart Load Error:", error);
        alert("Failed to load chart data.");
    }
}

// Auto-resize chart on window resize
window.addEventListener('resize', () => {
    chart.applyOptions({ 
        width: document.getElementById('chart-container').clientWidth,
        height: document.getElementById('chart-container').clientHeight 
    });
});

// Load default on startup
window.onload = loadChartData;
