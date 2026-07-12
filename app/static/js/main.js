/**
 * HeatSense JavaScript Client Controller - Module 8
 * Manages premium navigation, AJAX requests, map controls, interactive legends,
 * search functionality, reports downloading, and dynamic UI rendering.
 */

function _rankEmoji(rank) {
    const map = { 1: '🥇', 2: '🥈', 3: '🥉' };
    return map[rank] || `${rank}.`;
}

document.addEventListener('DOMContentLoaded', function () {
    console.log("HeatSense Application Dashboard Initialized.");

    // Core variables
    let currentCHIValue = 0.50; // Cache for the interactive HHRI calculator
    
    // UI Elements
    const globalDistrictSelect = document.getElementById('global-district-select');
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    const searchDistrictInput = document.getElementById('search-district');
    const btnDownloadReport = document.getElementById('btn-download-report');
    
    // Pages Switching Setup
    const navLinks = document.querySelectorAll('#dashboard-nav .nav-link');
    const pages = document.querySelectorAll('.dashboard-page');
    
    // Chart Loader
    const chartLoader = document.getElementById('chart-loader');

    // ────────────────────────────────────────────────────────────────────────
    // 1. Sidebar Navigation switching with transitions
    // ────────────────────────────────────────────────────────────────────────
    navLinks.forEach(link => {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            const targetPage = this.getAttribute('data-page');
            
            // Toggle sidebar active class
            navLinks.forEach(l => l.classList.remove('active'));
            this.classList.add('active');

            // Show target page panel
            pages.forEach(p => {
                p.classList.remove('active');
                if (p.id === `page-${targetPage}`) {
                    p.classList.add('active');
                }
            });

            // Handle map redraw / Plotly resize on tab display
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 100);
        });
    });

    // ────────────────────────────────────────────────────────────────────────
    // 2. Global search filter matching district list
    // ────────────────────────────────────────────────────────────────────────
    if (searchDistrictInput) {
        searchDistrictInput.addEventListener('input', function () {
            const query = this.value.toLowerCase().trim();
            const options = globalDistrictSelect.options;
            
            let matchedIndex = -1;
            for (let i = 0; i < options.length; i++) {
                const txt = options[i].text.toLowerCase();
                if (txt.includes(query)) {
                    matchedIndex = i;
                    break;
                }
            }
            
            if (matchedIndex !== -1) {
                globalDistrictSelect.selectedIndex = matchedIndex;
                // Trigger update analysis automatically
                globalDistrictSelect.dispatchEvent(new Event('change'));
            }
        });
    }

    // ────────────────────────────────────────────────────────────────────────
    // 3. Download report option
    // ────────────────────────────────────────────────────────────────────────
    if (btnDownloadReport) {
        btnDownloadReport.addEventListener('click', function () {
            const districtId = globalDistrictSelect.value;
            if (!districtId) {
                alert("Please select a district first.");
                return;
            }
            // Trigger download of markdown/text report
            window.open(`/api/download-report?district_id=${districtId}`, '_blank');
        });
    }

    const btnDownloadPDF = document.getElementById('btn-download-pdf');
    if (btnDownloadPDF) {
        btnDownloadPDF.addEventListener('click', function () {
            const districtId = globalDistrictSelect.value;
            if (!districtId) {
                alert("Please select a district first.");
                return;
            }
            // Trigger browser-print print-to-PDF page
            window.open(`/api/download-pdf?district_id=${districtId}`, '_blank');
        });
    }


    // ────────────────────────────────────────────────────────────────────────
    // 4. Central Update Analysis Trigger
    // ────────────────────────────────────────────────────────────────────────
    function updateDashboardAnalysis() {
        const districtId = globalDistrictSelect.value;
        if (!districtId) return;

        // Show spinner
        if (chartLoader) chartLoader.classList.remove('d-none');

        const start = startDateInput.value;
        const end = endDateInput.value;

        // Refresh maps iframes with query strings
        const homeMap = document.getElementById('home-map-iframe');
        const mainMap = document.getElementById('main-map-iframe');
        if (homeMap) homeMap.src = `/api/map-layers?start_date=${start}&end_date=${end}`;
        if (mainMap) mainMap.src = `/api/map-layers?start_date=${start}&end_date=${end}`;

        // 1. Get predictions
        fetch(`/api/predict?district_id=${districtId}`)
            .then(res => res.json())
            .then(data => {
                if (data.error) return;

                // Home stats
                _setEl('home-stat-name', data.district);
                _setEl('home-stat-chi', (data.current_chi || 0).toFixed(3));
                _setEl('home-stat-risk', data.current_risk_level || data.risk_level);
                _setEl('home-stat-advisory', data.current_advisory || data.advisory);
                
                // Risk color class updates
                const riskColorMap = {
                    'Low': '#27ae60', 'Moderate': '#f39c12',
                    'High': '#e67e22', 'Very High': '#ef4444'
                };
                const homeRiskEl = document.getElementById('home-stat-risk');
                if (homeRiskEl) {
                    homeRiskEl.style.color = riskColorMap[data.current_risk_level || data.risk_level] || '#fff';
                }

                currentCHIValue = data.current_chi || 0.50;

                // Prediction page
                _setEl('pred-page-lst', `${data.predicted_lst_celsius || '--'} °C`);
                _setEl('pred-page-chi', (data.current_chi || 0).toFixed(3));
                _setEl('pred-page-risk', data.current_risk_level || data.risk_level);
                _setEl('pred-page-future-chi', (data.future_chi || 0).toFixed(3));
                _setEl('pred-page-future-risk', data.future_risk_level || '--');
                _setEl('pred-page-advisory', data.current_advisory || data.advisory);

                // Risk classes for page items
                const prEl = document.getElementById('pred-page-risk');
                if (prEl) prEl.className = `fw-bold my-1 ${data.current_risk_level === 'Very High' ? 'text-danger' : 'text-warning'}`;

                // Pop alert warning toast if high risk
                const globalAlert = document.getElementById('dashboard-global-alert');
                const globalAlertText = document.getElementById('global-alert-text');
                if (globalAlert) {
                    const r = data.current_risk_level || data.risk_level;
                    if (r === 'High' || r === 'Very High') {
                        globalAlert.classList.remove('d-none');
                        if (globalAlertText) {
                            globalAlertText.textContent = `${data.district} is operating at ${r} risk levels (${(data.current_chi||0).toFixed(3)} CHI). Advisory: ${data.current_advisory}`;
                        }
                    } else {
                        globalAlert.classList.add('d-none');
                    }
                }

                // Update health sliders with current default values
                const sliderTemp = document.getElementById('slider-temp');
                if (sliderTemp) {
                    sliderTemp.value = Math.round(data.predicted_lst_celsius || 32);
                    document.getElementById('slider-temp-val').textContent = `${sliderTemp.value}°C`;
                    recalculateHHRI();
                }
            });

        // 2. Get history trends
        const trendDiv = document.getElementById('analysis-trend-chart');
        fetch(`/api/history?district_id=${districtId}`)
            .then(res => res.json())
            .then(graph => {
                if (trendDiv && graph.data) {
                    // Update Plotly configuration for glassmorphic transparent background
                    graph.layout.paper_bgcolor = 'rgba(0,0,0,0)';
                    graph.layout.plot_bgcolor = 'rgba(0,0,0,0)';
                    graph.layout.font = { color: '#94a3b8' };
                    Plotly.newPlot(trendDiv, graph.data, graph.layout, { responsive: true });
                }
            });

        // 3. Get Factor Analysis contributions
        const barDiv = document.getElementById('analysis-factor-bar-chart');
        const pieDiv = document.getElementById('analysis-factor-pie-chart');
        const ribbon = document.getElementById('analysis-factor-ribbon');

        fetch('/api/factor-analysis')
            .then(res => res.json())
            .then(data => {
                if (data.error) return;

                // Build factor badges ribbon
                if (ribbon && data.ranked_factors) {
                    ribbon.innerHTML = '';
                    data.ranked_factors.forEach(f => {
                        const badge = document.createElement('span');
                        badge.className = 'badge rounded-pill px-3 py-2 d-flex align-items-center gap-1';
                        badge.style.cssText = `background:${f.colour};color:#fff;font-size:0.8rem;`;
                        badge.innerHTML = `<span>${_rankEmoji(f.rank)}</span> <strong>#${f.rank}</strong>&nbsp;${f.label} <span style="opacity:0.8;">&nbsp;${f.percentage}%</span>`;
                        ribbon.appendChild(badge);
                    });
                }

                const trans = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#94a3b8' } };
                if (barDiv && data.bar_chart_json) {
                    const spec = JSON.parse(data.bar_chart_json);
                    Plotly.newPlot(barDiv, spec.data, Object.assign(spec.layout, trans), { responsive: true });
                }
                if (pieDiv && data.pie_chart_json) {
                    const spec = JSON.parse(data.pie_chart_json);
                    Plotly.newPlot(pieDiv, spec.data, Object.assign(spec.layout, trans), { responsive: true });
                }

                if (chartLoader) chartLoader.classList.add('d-none');
            })
            .catch(() => {
                if (chartLoader) chartLoader.classList.add('d-none');
            });
    }

    // Trigger update on district change
    if (globalDistrictSelect) {
        globalDistrictSelect.addEventListener('change', updateDashboardAnalysis);
    }
    
    // GEE Refresh Button
    const btnUpdateMap = document.getElementById('btn-update-map');
    if (btnUpdateMap) {
        btnUpdateMap.addEventListener('click', updateDashboardAnalysis);
    }

    // ────────────────────────────────────────────────────────────────────────
    // 5. GEE Layer checkboxes & interactive legends
    // ────────────────────────────────────────────────────────────────────────
    const layerChecks = {
        'layer-lst':  'lst',
        'layer-ndvi': 'ndvi',
        'layer-ndbi': 'ndbi',
        'layer-lulc': 'lulc',
        'layer-air':  'air'
    };

    const legendTitles = {
        'lst':  'Land Surface Temp (°C)',
        'ndvi': 'Vegetation Index (NDVI)',
        'ndbi': 'Built-Up Index (NDBI)',
        'lulc': 'ESA Land Use Class Colors',
        'air':  'Ambient Air Temp (2m - °C)'
    };

    const legendGradients = {
        'lst': [
            { c: '#0000ff', l: '< 20°C (Cool)' },
            { c: '#00ffff', l: '20°C - 30°C' },
            { c: '#ffff00', l: '30°C - 40°C' },
            { c: '#ff7f00', l: '40°C - 45°C' },
            { c: '#ff0000', l: '> 45°C (Extreme)' }
        ],
        'ndvi': [
            { c: '#ffffff', l: '< 0.0 (Barren)' },
            { c: '#f7fcb9', l: '0.0 - 0.2 (Sparse)' },
            { c: '#addd8e', l: '0.2 - 0.4 (Shrub)' },
            { c: '#31a354', l: '0.4 - 0.6 (Medium)' },
            { c: '#006837', l: '> 0.6 (Dense Forest)' }
        ],
        'ndbi': [
            { c: '#0000ff', l: '< -0.3 (Non-Urban)' },
            { c: '#ffffff', l: '-0.3 - 0.0' },
            { c: '#ff0000', l: '> 0.0 (High Impervious/Concrete)' }
        ],
        'lulc': [
            { c: '#006400', l: 'Trees' },
            { c: '#ffbb22', l: 'Shrubland' },
            { c: '#ffff4c', l: 'Grassland' },
            { c: '#f096ff', l: 'Cropland' },
            { c: '#fa0000', l: 'Built-up / Urban concrete' },
            { c: '#0064c8', l: 'Open water / Wetland' }
        ],
        'air': [
            { c: '#1a9850', l: '< 22°C (Comfort)' },
            { c: '#fee08b', l: '22°C - 32°C' },
            { c: '#d73027', l: '> 32°C (Warming)' }
        ]
    };

    Object.keys(layerChecks).forEach(chkId => {
        const checkbox = document.getElementById(chkId);
        if (checkbox) {
            checkbox.addEventListener('change', function () {
                if (this.checked) {
                    // Turn off other checkboxes to focus map layer
                    Object.keys(layerChecks).forEach(otherId => {
                        if (otherId !== chkId) {
                            const oc = document.getElementById(otherId);
                            if (oc) oc.checked = false;
                        }
                    });
                    
                    // Update Legend Box details
                    const key = layerChecks[chkId];
                    document.getElementById('legend-title').textContent = legendTitles[key];
                    
                    const container = document.getElementById('legend-items');
                    container.innerHTML = '';
                    legendGradients[key].forEach(item => {
                        const div = document.createElement('div');
                        div.className = 'legend-item';
                        div.innerHTML = `<span class="legend-color" style="background:${item.c};"></span> ${item.l}`;
                        container.appendChild(div);
                    });
                }
            });
        }
    });

    // ────────────────────────────────────────────────────────────────────────
    // 6. Mitigation Strategies Simulations triggers
    // ────────────────────────────────────────────────────────────────────────
    const btnRunStrategy = document.getElementById('btn-run-strategy');
    if (btnRunStrategy) {
        btnRunStrategy.addEventListener('click', function () {
            const districtId = globalDistrictSelect.value;
            const strategyType = document.getElementById('strategy-select').value;
            
            btnRunStrategy.textContent = '⏳ Simulating…';
            btnRunStrategy.disabled = true;

            fetch('/api/mitigation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    district_id: districtId,
                    scenario_type: strategyType
                })
            })
            .then(res => res.json())
            .then(data => {
                btnRunStrategy.textContent = '▶ Run Mitigation';
                btnRunStrategy.disabled = false;

                if (data.error) {
                    alert('Simulation failed: ' + data.error);
                    return;
                }

                // Populate page 6 (Mitigation results) details
                _setEl('mit-before', (data.before_chi || 0).toFixed(3));
                _setEl('mit-after', (data.after_chi || 0).toFixed(3));
                _setEl('mit-temp', `${(data.lst_reduction || 0).toFixed(1)} °C`);
                _setEl('mit-pct-val', `${(data.pct_improvement || 0).toFixed(1)}%`);
                _setEl('mit-desc-text', `Intervention Details: ${data.description}. Post-simulation composite index represents an improvement of ${data.pct_improvement}% reduction in local warming stress levels.`);

                // Update page 7 (Before vs After comparison page) Plotly charts
                const cfg = { responsive: true, displayModeBar: false };
                const trans = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#94a3b8' } };
                
                _renderPlotly('comp-indicator-chart', data.indicator_json, trans, cfg);
                _renderPlotly('comp-chi-chart', data.chi_bar_json, trans, cfg);
                _renderPlotly('comp-lst-chart', data.lst_bar_json, trans, cfg);
                _renderPlotly('comp-delta-chart', data.delta_bar_json, trans, cfg);

                // Auto switch page view to Before/After for wow factor
                const beforeAfterLink = document.querySelector('[data-page="before-after"]');
                if (beforeAfterLink) beforeAfterLink.click();
            })
            .catch(err => {
                btnRunStrategy.textContent = '▶ Run Mitigation';
                btnRunStrategy.disabled = false;
                console.error("Simulation run error:", err);
            });
        });
    }

    function _renderPlotly(divId, jsonStr, layoutOverride, config) {
        if (!jsonStr) return;
        const div = document.getElementById(divId);
        if (!div) return;
        try {
            const spec = JSON.parse(jsonStr);
            Object.assign(spec.layout, layoutOverride);
            Plotly.newPlot(div, spec.data, spec.layout, config);
        } catch (e) {
            console.warn(`Chart drawing failed on #${divId}:`, e);
        }
    }

    // ────────────────────────────────────────────────────────────────────────
    // 7. Interactive HHRI calculator logic (sliders)
    // ────────────────────────────────────────────────────────────────────────
    const sliderTemp = document.getElementById('slider-temp');
    const sliderRh = document.getElementById('slider-rh');
    const sliderVuln = document.getElementById('slider-vuln');

    function recalculateHHRI() {
        if (!sliderTemp || !sliderRh || !sliderVuln) return;

        const temp = parseFloat(sliderTemp.value);
        const rh = parseFloat(sliderRh.value);
        const vuln = parseFloat(sliderVuln.value);

        // Update slider feedback labels
        document.getElementById('slider-temp-val').textContent = `${temp}°C`;
        document.getElementById('slider-rh-val').textContent = `${rh}%`;
        document.getElementById('slider-vuln-val').textContent = vuln.toFixed(2);

        // Normalized values [0, 1] matching Python health_risk.py formula
        const air_n = Math.min(1, Math.max(0, (temp - 15.0) / 30.0));
        const rh_n  = Math.min(1, Math.max(0, (rh - 20.0) / 80.0));

        // HHRI = CHI * 0.40 + air_n * 0.25 + rh_n * 0.20 + vuln * 0.15
        const computedScore = (currentCHIValue * 0.40) + (air_n * 0.25) + (rh_n * 0.20) + (vuln * 0.15);
        const scoreVal = Math.min(1.0, Math.max(0.0, computedScore));

        document.getElementById('calc-risk-score').textContent = scoreVal.toFixed(3);

        // Define Risk Tiers
        let level = 'Low';
        let icon = '🟢';
        let adv = 'Conditions are normal. Stay hydrated and avoid prolonged sun exposure during afternoon hours.';
        let color = '#10b981';

        if (scoreVal >= 0.72) {
            level = 'Very High Risk';
            icon = '🔴';
            adv = 'EXTREME HEAT STRESS. Activate heat action plan. Open cooling centres, issue warning broadcasts, and limit outdoor labor.';
            color = '#ef4444';
        } else if (scoreVal >= 0.52) {
            level = 'High Risk';
            icon = '🟠';
            adv = 'High warning advisory. Drink fluids regularly, avoid peak sunlight hours, and deploy community health checkups.';
            color = '#f97316';
        } else if (scoreVal >= 0.30) {
            level = 'Moderate Risk';
            icon = '🟡';
            adv = 'Moderate heat index levels. Outdoor workers should take regular breaks and stay hydrated in shaded spots.';
            color = '#eab308';
        }

        const levelEl = document.getElementById('calc-risk-level');
        const iconEl  = document.getElementById('calc-risk-icon');
        const advEl   = document.getElementById('calc-risk-advisory');

        if (levelEl) {
            levelEl.textContent = level;
            levelEl.style.color = color;
        }
        if (iconEl) iconEl.textContent = icon;
        if (advEl) advEl.textContent = adv;
    }

    if (sliderTemp) sliderTemp.addEventListener('input', recalculateHHRI);
    if (sliderRh) sliderRh.addEventListener('input', recalculateHHRI);
    if (sliderVuln) sliderVuln.addEventListener('input', recalculateHHRI);

    // ────────────────────────────────────────────────────────────────────────
    // 8. Alerts Warnings log database table populator
    // ────────────────────────────────────────────────────────────────────────
    function fetchAndRenderAlerts() {
        const body = document.getElementById('alerts-table-body');
        if (!body) return;

        fetch('/api/alerts')
            .then(res => res.json())
            .then(alerts => {
                body.innerHTML = '';
                if (alerts.length === 0) {
                    body.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">No active health warnings seeded in SQLite.</td></tr>`;
                    return;
                }

                alerts.forEach(a => {
                    let badge = `<span class="badge bg-success">Low</span>`;
                    if (a.risk_level === 'Very High') {
                        badge = `<span class="badge bg-danger">🔴 Very High</span>`;
                    } else if (a.risk_level === 'High') {
                        badge = `<span class="badge bg-warning text-dark">🟠 High</span>`;
                    } else if (a.risk_level === 'Moderate') {
                        badge = `<span class="badge bg-info text-dark">🟡 Moderate</span>`;
                    }

                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td class="ps-3 small text-muted">${a.alert_date}</td>
                        <td class="fw-semibold">${a.district_name}</td>
                        <td>${badge}</td>
                        <td class="small text-muted" style="max-width:320px;">${a.advisory_message}</td>
                        <td><span class="badge bg-success-subtle text-success border border-success">Active</span></td>
                    `;
                    body.appendChild(row);
                });
            });
    }

    // Trigger Initial Updates
    updateDashboardAnalysis();
    fetchAndRenderAlerts();
});

// Safe helper
function _setEl(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
