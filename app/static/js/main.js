/**
 * HeatSense — Main Dashboard JavaScript
 * Handles page navigation, API data loading, chart rendering,
 * mitigation simulation, before/after swipe, and age-specific alerts.
 */

(function () {
    'use strict';

    // ── Global State ──────────────────────────────────────────────────────
    const HS = window.HEATSENSE || { lat: 12.9716, lon: 77.5946, name: 'Bengaluru Urban', radius: 15 };
    let currentPage = 'home';
    let selectedStrategy = 'vegetation_expansion';
    let predictionData = null;
    let factorData = null;
    let healthData = null;

    // ── Page Navigation ───────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        initNavigation();
        // Load home data on startup
        loadPrediction();
        loadHealthRisk();
    });

    function initNavigation() {
        const navLinks = document.querySelectorAll('#dashboard-nav .nav-link');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = link.dataset.page;
                switchPage(page);
            });
        });
    }

    function switchPage(page) {
        // Hide all pages
        document.querySelectorAll('.dashboard-page').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('#dashboard-nav .nav-link').forEach(l => l.classList.remove('active'));

        // Show target page
        const target = document.getElementById('page-' + page);
        if (target) {
            target.classList.add('active');
            currentPage = page;
        }

        // Highlight nav link
        const navLink = document.querySelector(`#dashboard-nav .nav-link[data-page="${page}"]`);
        if (navLink) navLink.classList.add('active');

        // Lazy-load page data on first visit
        if (page === 'trends') loadTrends();
        if (page === 'prediction') loadPredictionChart();
        if (page === 'factor-analysis') loadFactorAnalysis();
        if (page === 'health-risk') loadHealthRisk();
        if (page === 'alerts-precautions') loadAlertsPrecautions();
    }

    // ── API Helper ────────────────────────────────────────────────────────
    function apiUrl(path) {
        const sep = path.includes('?') ? '&' : '?';
        return `${path}${sep}lat=${HS.lat}&lon=${HS.lon}&name=${encodeURIComponent(HS.name)}&radius=${HS.radius}`;
    }

    function fetchJSON(url) {
        return fetch(url).then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        });
    }

    // ── HOME: Load Predictions (populates home stats + prediction page) ──
    function loadPrediction() {
        fetchJSON(apiUrl('/api/predict'))
            .then(data => {
                predictionData = data;
                updateHomeDashboard(data);
                updatePredictionPage(data);
            })
            .catch(err => {
                console.error('Prediction load failed:', err);
                setEl('home-stat-chi', 'Error');
            });
    }

    function updateHomeDashboard(data) {
        setEl('home-stat-chi', data.current_chi.toFixed(3));
        setEl('home-stat-lst', data.predicted_lst_celsius.toFixed(1) + '°C');
        setEl('home-stat-risk', data.current_risk_level);
        setEl('home-stat-advisory', data.current_advisory);

        // Color risk level
        const riskEl = document.getElementById('home-stat-risk');
        if (riskEl) riskEl.style.color = riskColor(data.current_risk_level);

        // Environmental factors
        if (data.features) {
            setEl('home-air-temp', (data.features.air_temp || 0).toFixed(1) + '°C');
            setEl('home-humidity', (data.features.relative_humidity || 0).toFixed(1) + '%');
            setEl('home-ndvi', (data.features.ndvi || 0).toFixed(3));
            setEl('home-ndbi', (data.features.ndbi || 0).toFixed(3));
            setEl('home-wind', (data.features.wind_speed || 0).toFixed(1) + ' m/s');
            setEl('home-lulc', (data.features.lulc_heat || 0).toFixed(3));
        }

        setEl('home-future-chi', data.future_chi.toFixed(3));
        setEl('home-data-source', 'Data source: ' + (data.data_source === 'gee' ? '🛰️ Google Earth Engine' : '📊 Climatological Model'));

        // Map GEE badge
        const mapBadge = document.getElementById('map-gee-badge');
        const mapText = document.getElementById('map-gee-text');
        if (mapBadge && mapText) {
            if (data.data_source === 'gee') {
                mapBadge.className = 'gee-badge online';
                mapText.textContent = 'GEE Layers';
            } else {
                mapBadge.className = 'gee-badge offline';
                mapText.textContent = 'Basemap';
            }
        }

        // Alert banner for high/very high
        if (data.current_risk_level === 'High' || data.current_risk_level === 'Very High') {
            const alertDiv = document.getElementById('dashboard-alert');
            if (alertDiv) {
                alertDiv.classList.remove('d-none');
                setEl('dashboard-alert-text', data.current_advisory);
            }
        }
    }

    function updatePredictionPage(data) {
        setEl('pred-lst', data.predicted_lst_celsius.toFixed(1) + '°C');
        setEl('pred-chi', data.current_chi.toFixed(3));
        setEl('pred-risk', data.current_risk_level);
        setEl('pred-future-chi', data.future_chi.toFixed(3));
        setEl('pred-future-risk', data.future_risk_level);
        setEl('pred-advisory', data.future_advisory);

        const riskEl = document.getElementById('pred-risk');
        if (riskEl) riskEl.style.color = riskColor(data.current_risk_level);
        const futRiskEl = document.getElementById('pred-future-risk');
        if (futRiskEl) futRiskEl.style.color = riskColor(data.future_risk_level);
    }

    // ── TRENDS ────────────────────────────────────────────────────────────
    let trendsLoaded = false;
    window.loadTrends = function () {
        const startYear = document.getElementById('trend-start-year')?.value || 2015;
        const endYear = document.getElementById('trend-end-year')?.value || 2025;

        const chartDiv = document.getElementById('trend-chart');
        chartDiv.innerHTML = '<div class="loading-overlay"><div class="hs-spinner"></div><span>Loading trend analysis...</span></div>';

        fetchJSON(apiUrl(`/api/history?start_year=${startYear}&end_year=${endYear}`))
            .then(data => {
                if (data.chart && data.chart.data) {
                    Plotly.newPlot('trend-chart', data.chart.data, data.chart.layout, {
                        responsive: true,
                        displayModeBar: true,
                        displaylogo: false,
                    });
                }
                // Update slope info
                if (data.data && data.data.length > 0) {
                    const last = data.data[data.data.length - 1];
                    setEl('trend-slope-info',
                        `Warming rate: +${last.lst_slope.toFixed(3)}°C/year | ` +
                        `Latest LST: ${last.mean_lst_celsius.toFixed(1)}°C | ` +
                        `Latest CHI: ${last.mean_chi.toFixed(3)} | ` +
                        `Data source: ${last.data_source === 'gee' ? 'Google Earth Engine' : 'Climatological Model'}`);
                }
                trendsLoaded = true;
            })
            .catch(err => {
                console.error('Trends failed:', err);
                chartDiv.innerHTML = '<div class="loading-overlay text-danger">Failed to load trend data.</div>';
            });
    };

    // ── PREDICTION CHART ──────────────────────────────────────────────────
    let predChartLoaded = false;
    function loadPredictionChart() {
        if (predChartLoaded) return;
        const chartDiv = document.getElementById('prediction-chart');
        chartDiv.innerHTML = '<div class="loading-overlay"><div class="hs-spinner"></div><span>Generating predictions...</span></div>';

        fetchJSON(apiUrl('/api/history'))
            .then(data => {
                if (data.data) {
                    // Use visualization module's prediction chart
                    const historicalData = data.data;
                    const futureData = predictionData || {};

                    // Build prediction-focused chart client-side
                    const years = historicalData.map(d => d.year);
                    const chiVals = historicalData.map(d => d.mean_chi);

                    // Linear regression for projection
                    const n = years.length;
                    const sumX = years.reduce((a, b) => a + b, 0);
                    const sumY = chiVals.reduce((a, b) => a + b, 0);
                    const sumXY = years.reduce((sum, x, i) => sum + x * chiVals[i], 0);
                    const sumX2 = years.reduce((sum, x) => sum + x * x, 0);
                    const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
                    const intercept = (sumY - slope * sumX) / n;

                    const lastYear = Math.max(...years);
                    const projYears = [];
                    const projChi = [];
                    for (let y = lastYear + 1; y <= lastYear + 10; y++) {
                        projYears.push(y);
                        projChi.push(Math.min(1.0, slope * y + intercept));
                    }

                    const traces = [
                        {
                            x: years, y: chiVals,
                            mode: 'lines+markers', name: 'Historical CHI',
                            fill: 'tozeroy', fillcolor: 'rgba(249,115,22,0.1)',
                            line: { color: '#f97316', width: 3 },
                            marker: { size: 7 },
                        },
                        {
                            x: [lastYear, ...projYears], y: [chiVals[chiVals.length - 1], ...projChi],
                            mode: 'lines+markers', name: 'Projected CHI',
                            fill: 'tozeroy', fillcolor: 'rgba(239,68,68,0.08)',
                            line: { color: '#ef4444', width: 2, dash: 'dash' },
                            marker: { size: 5, symbol: 'diamond' },
                        },
                    ];

                    const layout = {
                        title: `Heat Prediction — ${HS.name}`,
                        xaxis: { title: 'Year', gridcolor: 'rgba(255,255,255,0.05)' },
                        yaxis: { title: 'CHI', range: [0, 1.1], gridcolor: 'rgba(255,255,255,0.05)' },
                        paper_bgcolor: 'rgba(0,0,0,0)',
                        plot_bgcolor: 'rgba(0,0,0,0)',
                        legend: { orientation: 'h', x: 0, y: -0.15, bgcolor: 'rgba(0,0,0,0)' },
                        margin: { l: 50, r: 50, t: 50, b: 80 },
                        shapes: [{
                            type: 'line', x0: lastYear + 0.5, x1: lastYear + 0.5, y0: 0, y1: 1,
                            line: { color: 'rgba(255,255,255,0.2)', dash: 'dot' },
                        }],
                    };

                    Plotly.newPlot('prediction-chart', traces, layout, { responsive: true, displaylogo: false });
                    predChartLoaded = true;
                }
            })
            .catch(err => {
                console.error('Prediction chart failed:', err);
                chartDiv.innerHTML = '<div class="loading-overlay text-danger">Failed to load prediction data.</div>';
            });
    }

    // ── FACTOR ANALYSIS ───────────────────────────────────────────────────
    let factorLoaded = false;
    function loadFactorAnalysis() {
        if (factorLoaded) return;

        fetchJSON(apiUrl('/api/factor-analysis'))
            .then(data => {
                factorData = data;

                // Render radar chart
                if (data.radar_chart_json) {
                    const radarData = JSON.parse(data.radar_chart_json);
                    Plotly.newPlot('radar-chart', radarData.data, radarData.layout, {
                        responsive: true,
                        displaylogo: false,
                        displayModeBar: false,
                    });
                }

                // Render factor score cards
                if (data.factor_scores) {
                    renderFactorCards(data.factor_scores);
                }

                // Render bar chart (RF feature importance)
                if (data.bar_chart_json) {
                    try {
                        const barData = JSON.parse(data.bar_chart_json);
                        Plotly.newPlot('factor-bar-chart', barData.data, barData.layout, { responsive: true, displaylogo: false });
                    } catch (e) { }
                }

                // Render pie chart
                if (data.pie_chart_json) {
                    try {
                        const pieData = JSON.parse(data.pie_chart_json);
                        Plotly.newPlot('factor-pie-chart', pieData.data, pieData.layout, { responsive: true, displaylogo: false });
                    } catch (e) { }
                }

                // Key findings text
                if (data.factor_scores && data.factor_scores.length > 0) {
                    const sorted = [...data.factor_scores].sort((a, b) => b.score - a.score);
                    const top3 = sorted.slice(0, 3).map(f => f.label).join(', ');
                    setEl('factor-findings',
                        `The top contributing heat factors for ${HS.name} are: ${top3}. ` +
                        `Data source: ${data.data_source === 'gee' ? 'Google Earth Engine satellite imagery' : 'Climatological regression model'}.`
                    );
                }

                factorLoaded = true;
            })
            .catch(err => {
                console.error('Factor analysis failed:', err);
                document.getElementById('radar-chart').innerHTML = '<div class="loading-overlay text-danger">Failed to load factor data.</div>';
            });
    }

    function renderFactorCards(factors) {
        const container = document.getElementById('factor-scores-container');
        container.innerHTML = factors.map(f => `
            <div class="factor-card mb-2">
                <span class="factor-icon">${f.icon}</span>
                <div class="flex-grow-1">
                    <div class="d-flex justify-content-between">
                        <span class="factor-label">${f.label}</span>
                        <span class="factor-value" style="color:${f.color};">${f.value}${f.unit ? ' ' + f.unit : ''}</span>
                    </div>
                    <div class="factor-bar">
                        <div class="factor-bar-fill" style="width:${f.score}%;background:${f.color};"></div>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <small style="font-size:0.65rem;color:var(--text-muted);">${f.direction === 'heat' ? '🔥 Heat factor' : '❄️ Cooling factor'}</small>
                        <small style="font-size:0.65rem;color:var(--text-muted);">${f.score}/100</small>
                    </div>
                </div>
            </div>
        `).join('');
    }

    // ── MITIGATION ────────────────────────────────────────────────────────
    window.selectStrategy = function (el) {
        document.querySelectorAll('.strategy-card').forEach(c => c.classList.remove('selected'));
        el.classList.add('selected');
        selectedStrategy = el.dataset.strategy;
    };

    window.runMitigation = function () {
        const btn = document.getElementById('btn-run-mitigation');
        btn.innerHTML = '<div class="hs-spinner" style="width:16px;height:16px;border-width:2px;"></div> Simulating...';
        btn.disabled = true;

        fetch('/api/mitigation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lat: HS.lat,
                lon: HS.lon,
                name: HS.name,
                radius: HS.radius,
                scenario_type: selectedStrategy,
            }),
        })
            .then(r => r.json())
            .then(data => {
                btn.innerHTML = '<i class="fa-solid fa-play me-1"></i> Run Simulation';
                btn.disabled = false;

                document.getElementById('mitigation-results').classList.remove('d-none');

                setEl('mit-before-chi', data.before_chi.toFixed(3));
                setEl('mit-after-chi', data.after_chi.toFixed(3));
                setEl('mit-lst-reduction', '-' + data.lst_reduction_celsius.toFixed(1) + '°C');
                const pct = ((data.before_chi - data.after_chi) / data.before_chi * 100).toFixed(1);
                setEl('mit-pct', '-' + pct + '%');

                // Before/After comparison chart
                const chiTrace = {
                    x: ['Before', 'After'],
                    y: [data.before_chi, data.after_chi],
                    type: 'bar',
                    marker: {
                        color: ['#ef4444', '#10b981'],
                        line: { width: 0 },
                    },
                    text: [data.before_chi.toFixed(3), data.after_chi.toFixed(3)],
                    textposition: 'outside',
                    textfont: { color: '#fff', size: 14 },
                };
                Plotly.newPlot('mit-chi-chart', [chiTrace], {
                    title: 'CHI Before vs After',
                    yaxis: { range: [0, 1], gridcolor: 'rgba(255,255,255,0.05)' },
                    xaxis: { },
                    paper_bgcolor: 'rgba(0,0,0,0)',
                    plot_bgcolor: 'rgba(0,0,0,0)',
                    margin: { t: 40, b: 40, l: 40, r: 20 },
                }, { responsive: true, displaylogo: false });

                // Gauge chart
                const gaugeTrace = {
                    type: 'indicator',
                    mode: 'gauge+number+delta',
                    value: data.after_chi,
                    delta: { reference: data.before_chi, decreasing: { color: '#10b981' } },
                    gauge: {
                        axis: { range: [0, 1] },
                        bar: { color: '#10b981' },
                        steps: [
                            { range: [0, 0.35], color: 'rgba(39,174,96,0.15)' },
                            { range: [0.35, 0.55], color: 'rgba(241,196,15,0.15)' },
                            { range: [0.55, 0.75], color: 'rgba(230,126,34,0.15)' },
                            { range: [0.75, 1], color: 'rgba(239,68,68,0.15)' },
                        ],
                        threshold: {
                            line: { color: '#ef4444', width: 3 },
                            thickness: 0.8,
                            value: data.before_chi,
                        },
                    },
                    title: { text: 'Post-Mitigation CHI' },
                };
                Plotly.newPlot('mit-gauge-chart', [gaugeTrace], {
                    paper_bgcolor: 'rgba(0,0,0,0)',
                    plot_bgcolor: 'rgba(0,0,0,0)',
                    margin: { t: 30, b: 10, l: 30, r: 30 },
                    font: { color: '#f5f5f5' },
                }, { responsive: true, displaylogo: false });
            })
            .catch(err => {
                console.error('Mitigation failed:', err);
                btn.innerHTML = '<i class="fa-solid fa-play me-1"></i> Run Simulation';
                btn.disabled = false;
            });
    };

    // ── BEFORE & AFTER ────────────────────────────────────────────────────
    window.loadBeforeAfter = function () {
        const strategy = document.getElementById('ba-strategy')?.value || 'vegetation_expansion';
        const loading = document.getElementById('ba-loading');
        const stats = document.getElementById('ba-stats');
        loading.style.display = 'flex';
        stats.style.display = 'none';

        fetchJSON(apiUrl(`/api/before-after-maps?strategy=${strategy}`))
            .then(data => {
                // Load HTML into iframes via srcdoc
                const beforeIframe = document.getElementById('ba-before-iframe');
                const afterIframe = document.getElementById('ba-after-iframe');
                beforeIframe.srcdoc = data.before_html;
                afterIframe.srcdoc = data.after_html;
                loading.style.display = 'none';

                // Also run mitigation to get delta stats
                return fetch('/api/mitigation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lat: HS.lat, lon: HS.lon, name: HS.name, radius: HS.radius, scenario_type: strategy }),
                });
            })
            .then(r => r.json())
            .then(mitData => {
                stats.style.display = '';
                stats.style.display = 'flex';
                const chiDelta = (mitData.before_chi - mitData.after_chi).toFixed(3);
                setEl('ba-chi-delta', '-' + chiDelta);
                setEl('ba-lst-delta', '-' + mitData.lst_reduction_celsius.toFixed(1) + '°C');
                setEl('ba-risk-before', mitData.before_risk || '—');
                setEl('ba-risk-after', mitData.after_risk || '—');
            })
            .catch(err => {
                console.error('Before/After failed:', err);
                loading.innerHTML = '<span class="text-danger">Failed to load comparison.</span>';
            });
    };

    // Initialize Before/After swipe slider
    function initSwipeSlider() {
        const wrapper = document.getElementById('ba-wrapper');
        const slider = document.getElementById('ba-slider');
        const before = document.getElementById('ba-before');
        if (!wrapper || !slider || !before) return;

        let isDragging = false;

        function setPosition(x) {
            const rect = wrapper.getBoundingClientRect();
            let pct = ((x - rect.left) / rect.width) * 100;
            pct = Math.max(5, Math.min(95, pct));
            slider.style.left = pct + '%';
            before.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
        }

        slider.addEventListener('mousedown', () => { isDragging = true; });
        window.addEventListener('mouseup', () => { isDragging = false; });
        window.addEventListener('mousemove', (e) => { if (isDragging) setPosition(e.clientX); });

        // Touch support
        slider.addEventListener('touchstart', () => { isDragging = true; });
        window.addEventListener('touchend', () => { isDragging = false; });
        window.addEventListener('touchmove', (e) => {
            if (isDragging && e.touches.length) setPosition(e.touches[0].clientX);
        });
    }
    document.addEventListener('DOMContentLoaded', initSwipeSlider);

    // ── HEALTH RISK ───────────────────────────────────────────────────────
    function loadHealthRisk() {
        fetchJSON(apiUrl('/api/health-risk'))
            .then(data => {
                healthData = data;
                setEl('hr-hhri', data.hhri.toFixed(3));
                setEl('hr-chi', data.chi.toFixed(3));
                setEl('hr-advisory', data.advisory);

                const hhriEl = document.getElementById('hr-hhri');
                if (hhriEl) hhriEl.style.color = riskColor(data.risk_level);

                const badgeDiv = document.getElementById('hr-risk-badge');
                if (badgeDiv) {
                    const cls = data.risk_level.toLowerCase().replace(' ', '');
                    badgeDiv.innerHTML = `<span class="risk-badge ${cls}">${data.risk_icon} ${data.risk_level} — ${data.action}</span>`;
                }
            })
            .catch(err => console.error('Health risk failed:', err));
    }

    // ── ALERTS & AGE PRECAUTIONS ──────────────────────────────────────────
    let alertsLoaded = false;
    function loadAlertsPrecautions() {
        if (alertsLoaded) return;

        // Load age-specific precautions
        fetchJSON(apiUrl('/api/health-risk'))
            .then(data => {
                const container = document.getElementById('age-cards-container');
                if (data.age_precautions && data.age_precautions.length > 0) {
                    container.innerHTML = data.age_precautions.map(group => `
                        <div class="col-md-4 col-lg-4 mb-3">
                            <div class="age-card ${group.key}">
                                <div class="age-icon">${group.icon}</div>
                                <div class="age-title" style="color:${group.color};">${group.label}</div>
                                <ul class="precaution-list">
                                    ${group.precautions.map(p => `<li>${p}</li>`).join('')}
                                </ul>
                            </div>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<p class="text-muted">No precaution data available.</p>';
                }
            })
            .catch(err => {
                console.error('Precautions failed:', err);
                document.getElementById('age-cards-container').innerHTML = '<p class="text-danger">Failed to load precautions.</p>';
            });

        // Load system alerts
        fetchJSON('/api/alerts')
            .then(alerts => {
                const container = document.getElementById('system-alerts-container');
                if (alerts.length === 0) {
                    container.innerHTML = '<p class="text-muted">No active alerts.</p>';
                    return;
                }
                container.innerHTML = alerts.slice(0, 10).map(a => {
                    const cls = a.risk_level === 'Very High' ? 'danger' : a.risk_level === 'High' ? 'warning' : 'secondary';
                    return `
                    <div class="alert-toast mb-2">
                        <span class="fs-4">${a.risk_level === 'Very High' ? '🔴' : a.risk_level === 'High' ? '🟠' : '🟡'}</span>
                        <div class="flex-grow-1">
                            <div class="d-flex justify-content-between">
                                <strong style="font-size:0.85rem;">${a.district_name}</strong>
                                <span class="badge bg-${cls}" style="font-size:0.7rem;">${a.risk_level}</span>
                            </div>
                            <small class="text-muted">${a.advisory_message.substring(0, 150)}...</small>
                            <div class="text-muted" style="font-size:0.7rem;">Date: ${a.alert_date} | Status: ${a.status}</div>
                        </div>
                    </div>`;
                }).join('');
                alertsLoaded = true;
            })
            .catch(err => {
                console.error('Alerts fetch failed:', err);
                document.getElementById('system-alerts-container').innerHTML = '<p class="text-danger">Failed to load alerts.</p>';
            });

        alertsLoaded = true;
    }

    // ── REPORTS ───────────────────────────────────────────────────────────
    window.downloadReport = function (type) {
        const params = `lat=${HS.lat}&lon=${HS.lon}&name=${encodeURIComponent(HS.name)}&radius=${HS.radius}`;
        if (type === 'pdf') {
            window.open(`/api/download-pdf?${params}`, '_blank');
        } else {
            window.location.href = `/api/download-report?${params}`;
        }
    };

    // ── MAP REFRESH ───────────────────────────────────────────────────────
    window.refreshMap = function () {
        const iframe = document.getElementById('main-map-iframe');
        if (iframe) {
            iframe.src = apiUrl('/api/map-layers');
        }
    };

    // ── UTILITY ───────────────────────────────────────────────────────────
    function setEl(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function riskColor(level) {
        const colors = {
            'Low': '#10b981',
            'Moderate': '#eab308',
            'High': '#e67e22',
            'Very High': '#ef4444',
        };
        return colors[level] || '#f5f5f5';
    }

})();
