// PartnerPulse Dashboard Application Logic
document.addEventListener("DOMContentLoaded", () => {
    // Check if PARTNER_DATA is loaded
    if (typeof PARTNER_DATA === "undefined") {
        console.error("PARTNER_DATA is not loaded! Make sure data.js is referenced correctly.");
        return;
    }
    
    // State management
    const state = {
        activeTab: "overview", // overview, actions, feedback, transcripts
        csatFilter: "All",     // All, Positive, Neutral, Negative
        feedbackTab: "csat",   // csat, nps
        selectedTranscriptIndex: 0,
        transcriptSearchQuery: "",
        activeKeywordFilter: "" // empty or specific keyword
    };

    // DOM Elements
    const elements = {
        navLinks: document.querySelectorAll(".nav-link-item"),
        pages: document.querySelectorAll(".page-container"),
        clientName: document.getElementById("client-name"),
        clientRagBadge: document.getElementById("client-rag-badge"),
        clientRiskBadge: document.getElementById("client-risk-badge"),
        
        // Overview Elements
        ovAM: document.getElementById("ov-am"),
        ovService: document.getElementById("ov-service"),
        ovHealthReason: document.getElementById("ov-health-reason"),
        ovNextStep: document.getElementById("ov-next-step"),
        ovSipTicket: document.getElementById("ov-sip-ticket"),
        ovCsatScore: document.getElementById("ov-csat-score"),
        ovNpsScore: document.getElementById("ov-nps-score"),
        ovSipProgressFill: document.getElementById("ov-sip-progress-fill"),
        ovSipProgressLabel: document.getElementById("ov-sip-progress-label"),
        ovStackedBar: document.getElementById("ov-stacked-bar"),
        ovLegendPositive: document.getElementById("ov-legend-positive"),
        ovLegendNeutral: document.getElementById("ov-legend-neutral"),
        ovLegendNegative: document.getElementById("ov-legend-negative"),
        ovLegendUnrated: document.getElementById("ov-legend-unrated"),
        ovRecentActionsBody: document.getElementById("ov-recent-actions-body"),
        
        // Actions Elements
        actionTableBody: document.getElementById("action-table-body"),
        accordionList: document.getElementById("accordion-list"),
        
        // Feedback Elements
        feedbackTabCsat: document.getElementById("tab-btn-csat"),
        feedbackTabNps: document.getElementById("tab-btn-nps"),
        csatFiltersContainer: document.getElementById("csat-filters-container"),
        csatFilterAll: document.getElementById("pill-all"),
        csatFilterPos: document.getElementById("pill-pos"),
        csatFilterNeu: document.getElementById("pill-neu"),
        csatFilterNeg: document.getElementById("pill-neg"),
        feedbackGrid: document.getElementById("feedback-grid"),
        
        // Transcripts Elements
        transcriptListPanel: document.getElementById("transcript-option-list"),
        dialogueTitle: document.getElementById("dialogue-title"),
        dialogueSubtitle: document.getElementById("dialogue-subtitle"),
        dialogueStream: document.getElementById("dialogue-stream"),
        dialogueSearch: document.getElementById("dialogue-search"),
        keywordFilters: document.querySelectorAll(".keyword-pill")
    };

    // 1. Navigation Controller
    function setupNavigation() {
        elements.navLinks.forEach(item => {
            item.addEventListener("click", (e) => {
                e.preventDefault();
                const tab = item.getAttribute("data-tab");
                
                // Update active navigation item styling
                elements.navLinks.forEach(link => link.closest(".nav-item").classList.remove("active"));
                item.closest(".nav-item").classList.add("active");
                
                // Show selected page
                elements.pages.forEach(page => {
                    page.classList.remove("active");
                    if (page.id === `page-${tab}`) {
                        page.classList.add("active");
                    }
                });
                
                state.activeTab = tab;
                
                // Render page-specific elements if necessary
                if (tab === "transcripts") {
                    renderTranscriptDialogue();
                }
            });
        });
    }

    // 2. Initialize Header & Meta Info
    function initClientMeta() {
        const client = PARTNER_DATA.client;
        elements.clientName.textContent = client.name;
        
        // Update badges
        elements.clientRagBadge.className = `badge badge-rag-amber`;
        elements.clientRagBadge.innerHTML = `<span class="legend-dot" style="background-color: var(--warning)"></span> RAG: ${client.rag}`;
        
        elements.clientRiskBadge.className = `badge badge-risk-low`;
        elements.clientRiskBadge.innerHTML = `<span class="legend-dot" style="background-color: var(--success)"></span> Churn Risk: ${client.cancel_risk}`;
        
        // Overview Profile
        elements.ovAM.textContent = client.account_manager;
        elements.ovService.textContent = client.service_line;
        elements.ovHealthReason.textContent = client.health_reason;
        elements.ovNextStep.textContent = client.next_step;
        
        if (client.sip_ticket) {
            elements.ovSipTicket.innerHTML = `<a href="#" style="color: var(--primary); font-weight: 600; text-decoration: none;">Ticket #${client.sip_ticket}</a>`;
        } else {
            elements.ovSipTicket.textContent = "N/A";
        }
        
        // Active Intervention Progress (Mock values based on Mazid's 2 weeks monitoring - 7 days completed)
        elements.ovSipProgressFill.style.width = "50%";
        elements.ovSipProgressLabel.textContent = "Monitoring Week 1 Completed (50%)";
    }

    // 3. Render Overview Section
    function renderOverview() {
        const csat = PARTNER_DATA.csat_stats;
        const totalCsat = csat.Positive + csat.Neutral + csat.Negative + csat.Unrated;
        const posPercent = ((csat.Positive / totalCsat) * 100).toFixed(1);
        
        // CSAT / NPS Top values
        elements.ovCsatScore.textContent = `${posPercent}%`;
        elements.ovNpsScore.textContent = `100%`; // Based on 19 Promoters
        
        // Render stacked bar chart
        const posWidth = (csat.Positive / totalCsat) * 100;
        const neuWidth = (csat.Neutral / totalCsat) * 100;
        const negWidth = (csat.Negative / totalCsat) * 100;
        const unWidth = (csat.Unrated / totalCsat) * 100;
        
        elements.ovStackedBar.innerHTML = `
            <div class="stacked-segment stacked-positive" style="width: ${posWidth}%" title="Positive: ${csat.Positive}"></div>
            <div class="stacked-segment stacked-neutral" style="width: ${neuWidth}%" title="Neutral: ${csat.Neutral}"></div>
            <div class="stacked-segment stacked-negative" style="width: ${negWidth}%" title="Negative: ${csat.Negative}"></div>
            <div class="stacked-segment stacked-unrated" style="width: ${unWidth}%" title="Unrated: ${csat.Unrated}"></div>
        `;
        
        // Legend labels
        elements.ovLegendPositive.textContent = `Positive: ${csat.Positive} (${posPercent}%)`;
        elements.ovLegendNeutral.textContent = `Neutral: ${csat.Neutral} (${((csat.Neutral / totalCsat) * 100).toFixed(1)}%)`;
        elements.ovLegendNegative.textContent = `Negative: ${csat.Negative} (${((csat.Negative / totalCsat) * 100).toFixed(1)}%)`;
        elements.ovLegendUnrated.textContent = `Unrated: ${csat.Unrated} (${((csat.Unrated / totalCsat) * 100).toFixed(1)}%)`;
        
        // Recent Action items (Overview list)
        const inProgressActions = PARTNER_DATA.action_items.filter(a => a.status !== "Completed").slice(0, 3);
        elements.ovRecentActionsBody.innerHTML = "";
        
        inProgressActions.forEach(act => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td style="font-weight: 500;">${act.task}</td>
                <td>${act.owner}</td>
                <td><span class="badge ${act.status === 'In Progress' ? 'badge-warning' : 'badge-danger'}">${act.status}</span></td>
            `;
            elements.ovRecentActionsBody.appendChild(tr);
        });
    }

    // 4. Render Action Tracker & Accordions
    function renderActionsPage() {
        // Render Action Items Table
        elements.actionTableBody.innerHTML = "";
        PARTNER_DATA.action_items.forEach(act => {
            const tr = document.createElement("tr");
            
            let statusBadge = "badge-info";
            if (act.status === "Completed") statusBadge = "badge-success";
            else if (act.status === "In Progress") statusBadge = "badge-warning";
            else if (act.status === "Pending") statusBadge = "badge-danger";
            
            tr.innerHTML = `
                <td style="font-weight: 600;">${act.task}</td>
                <td>${act.owner}</td>
                <td>${act.due}</td>
                <td><span class="badge ${statusBadge}">${act.status}</span></td>
                <td><span style="font-size: 0.8rem; color: var(--text-muted);">${act.source}</span></td>
            `;
            elements.actionTableBody.appendChild(tr);
        });
        
        // Render Collapsible Meeting Summaries (Accordions)
        elements.accordionList.innerHTML = "";
        PARTNER_DATA.historical_calls.forEach((call, index) => {
            const item = document.createElement("div");
            item.className = "accordion-item";
            if (index === 0) {
                // item.classList.add("active"); // don't open by default, let them click
            }
            
            // Format date nicely
            const d = new Date(call.date);
            const dateStr = d.toLocaleDateString("en-US", { year: 'numeric', month: 'long', day: 'numeric' });
            
            // Format note body: It has markdown-like headers. We will convert it to nice HTML
            let formattedNotes = call.notes
                .replace(/1\.\s+Meeting\s+Summary/gi, "<h4 class='notes-h4'>1. Meeting Summary</h4>")
                .replace(/2\.\s+Action\s+Items/gi, "<h4 class='notes-h4' style='margin-top: 16px;'>2. Action Items</h4>")
                .replace(/\n/g, "<br>");
                
            item.innerHTML = `
                <div class="accordion-header" data-index="${index}">
                    <div class="accordion-header-left">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width: 20px; height: 20px; color: var(--primary);">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
                        </svg>
                        <span class="accordion-title">${call.summary}</span>
                        <span class="accordion-date">${dateStr}</span>
                    </div>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="accordion-icon">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
                    </svg>
                </div>
                <div class="accordion-content">
                    <div class="accordion-body">
                        <div style="font-family: var(--font-body); font-size: 0.9rem; color: var(--text-secondary); line-height: 1.7;">
                            ${formattedNotes}
                        </div>
                    </div>
                </div>
            `;
            
            // Accordion click handler
            const header = item.querySelector(".accordion-header");
            header.addEventListener("click", () => {
                const isActive = item.classList.contains("active");
                // Collapse all
                document.querySelectorAll(".accordion-item").forEach(acc => acc.classList.remove("active"));
                
                if (!isActive) {
                    item.classList.add("active");
                }
            });
            
            elements.accordionList.appendChild(item);
        });
    }

    // 5. Render CSAT & NPS Feedback Page
    function setupFeedbackPage() {
        // Tab switching (CSAT vs NPS)
        elements.feedbackTabCsat.addEventListener("click", () => {
            elements.feedbackTabCsat.classList.add("active");
            elements.feedbackTabNps.classList.remove("active");
            elements.csatFiltersContainer.style.display = "flex";
            state.feedbackTab = "csat";
            renderFeedbackGrid();
        });
        
        elements.feedbackTabNps.addEventListener("click", () => {
            elements.feedbackTabNps.classList.add("active");
            elements.feedbackTabCsat.classList.remove("active");
            elements.csatFiltersContainer.style.display = "none";
            state.feedbackTab = "nps";
            renderFeedbackGrid();
        });
        
        // CSAT Filter pills click handler
        const filterPills = [elements.csatFilterAll, elements.csatFilterPos, elements.csatFilterNeu, elements.csatFilterNeg];
        filterPills.forEach(pill => {
            pill.addEventListener("click", () => {
                filterPills.forEach(p => p.classList.remove("active"));
                pill.classList.add("active");
                state.csatFilter = pill.getAttribute("data-filter");
                renderFeedbackGrid();
            });
        });
    }

    function renderFeedbackGrid() {
        elements.feedbackGrid.innerHTML = "";
        
        if (state.feedbackTab === "csat") {
            // Render CSAT list
            let list = PARTNER_DATA.csat_comments;
            if (state.csatFilter !== "All") {
                list = list.filter(c => c.rating === state.csatFilter);
            }
            
            if (list.length === 0) {
                elements.feedbackGrid.innerHTML = `<div class="no-results" style="grid-column: 1/-1;">No reviews found for filter "${state.csatFilter}".</div>`;
                return;
            }
            
            list.forEach(c => {
                const card = document.createElement("div");
                card.className = "feedback-card";
                
                let rBadgeClass = "badge-success";
                if (c.rating === "Neutral") rBadgeClass = "badge-warning";
                else if (c.rating === "Negative") rBadgeClass = "badge-danger";
                
                const d = new Date(c.date);
                const dateStr = d.toLocaleDateString("en-US", { month: 'short', day: 'numeric', year: 'numeric' });
                
                card.innerHTML = `
                    <div>
                        <div class="feedback-card-header">
                            <div class="feedback-author-info">
                                <span class="feedback-author-name">${c.contact || 'Anonymous'}</span>
                                <span class="feedback-date">${dateStr}</span>
                            </div>
                            <span class="badge ${rBadgeClass}">${c.rating}</span>
                        </div>
                        <div class="feedback-text">"${c.comment}"</div>
                    </div>
                    <div class="feedback-footer-details">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width: 14px; height: 14px;">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 6v.75m0 3v.75m0 3v.75m0 3V18m-9-5.25h5.25M7.5 15h3M3.375 5.25c-.621 0-1.125.504-1.125 1.125v3.026c0 .621.504 1.125 1.125 1.125h17.25c.621 0 1.125-.504 1.125-1.125V6.375c0-.621-.504-1.125-1.125-1.125H3.375Z" />
                        </svg>
                        Ticket: ${c.ticket_name} (ID: ${c.ticket_id})
                    </div>
                `;
                elements.feedbackGrid.appendChild(card);
            });
            
        } else {
            // Render NPS Client list
            const list = PARTNER_DATA.nps_comments;
            if (list.length === 0) {
                elements.feedbackGrid.innerHTML = `<div class="no-results" style="grid-column: 1/-1;">No client NPS comments logged.</div>`;
                return;
            }
            
            list.forEach(n => {
                const card = document.createElement("div");
                card.className = "feedback-card";
                
                const d = new Date(n.date);
                const dateStr = d.toLocaleDateString("en-US", { month: 'short', day: 'numeric', year: 'numeric' });
                
                card.innerHTML = `
                    <div>
                        <div class="feedback-card-header">
                            <div class="feedback-author-info">
                                <span class="feedback-author-name">${n.respondent}</span>
                                <span class="feedback-date">${dateStr}</span>
                            </div>
                            <span class="badge badge-success" style="font-size: 0.9rem; padding: 6px 12px; font-family: var(--font-heading);">Score: ${n.score}</span>
                        </div>
                        <div class="feedback-text">"${n.comment}"</div>
                    </div>
                    <div class="feedback-footer-details">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width: 14px; height: 14px;">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 0 1-4.5-4.5v-1.5a4.5 4.5 0 0 1 4.5-4.5h.75c.704 0 1.402-.03 2.09-.09m0 10.68c.688.06 1.386.09 2.09.09h1.9a15.6 15.6 0 0 0 9.17-2.9L21 12M10.34 5.16c.688-.06 1.386-.09 2.09-.09h1.9c3.72 0 7.12 1.3 9.77 3.48L21 12m0 0v5.671c0 .89-.597 1.686-1.455 1.96l-3.328 1.06a1.6 1.6 0 0 1-2.062-1.22L13.75 12" />
                        </svg>
                        Campaign: ${n.campaign}
                    </div>
                `;
                elements.feedbackGrid.appendChild(card);
            });
        }
    }

    // 6. Render Meeting Transcripts Explorer
    function initTranscriptsPage() {
        // Render Sidebar List
        elements.transcriptListPanel.innerHTML = "";
        
        PARTNER_DATA.transcripts.forEach((t, index) => {
            const item = document.createElement("div");
            item.className = `transcript-option-item ${index === state.selectedTranscriptIndex ? 'active' : ''}`;
            item.setAttribute("data-index", index);
            
            // Clean filename a bit
            const shortName = t.filename.replace(".docx", "").replace("Logically  _ ", "");
            
            item.innerHTML = `
                <div class="transcript-option-title">${shortName}</div>
                <div class="transcript-option-meta">
                    <span>${t.date}</span>
                    <span>${t.duration}</span>
                </div>
            `;
            
            item.addEventListener("click", () => {
                // Remove active styling from previous selection
                document.querySelectorAll(".transcript-option-item").forEach(el => el.classList.remove("active"));
                item.classList.add("active");
                
                state.selectedTranscriptIndex = index;
                renderTranscriptDialogue();
            });
            
            elements.transcriptListPanel.appendChild(item);
        });
        
        // Search listener
        elements.dialogueSearch.addEventListener("input", (e) => {
            state.transcriptSearchQuery = e.target.value.toLowerCase();
            renderTranscriptDialogue();
        });
        
        // Keyword Filter Pills listeners
        elements.keywordFilters.forEach(pill => {
            pill.addEventListener("click", () => {
                const keyword = pill.getAttribute("data-kw");
                if (state.activeKeywordFilter === keyword) {
                    // Toggle off
                    pill.classList.remove("active");
                    state.activeKeywordFilter = "";
                } else {
                    // Clear previous and set new
                    elements.keywordFilters.forEach(p => p.classList.remove("active"));
                    pill.classList.add("active");
                    state.activeKeywordFilter = keyword;
                }
                renderTranscriptDialogue();
            });
        });
    }

    function renderTranscriptDialogue() {
        const transcript = PARTNER_DATA.transcripts[state.selectedTranscriptIndex];
        if (!transcript) return;
        
        // Update header details
        elements.dialogueTitle.textContent = transcript.title;
        elements.dialogueSubtitle.textContent = `Date: ${transcript.date} | Duration: ${transcript.duration}`;
        
        elements.dialogueStream.innerHTML = "";
        
        let dialogueList = transcript.dialogue;
        
        // Apply search query and keyword filters
        const q = state.transcriptSearchQuery;
        const kw = state.activeKeywordFilter;
        
        // ITBD team members list to align chat bubble (Client left, ITBD right)
        const itbdSpeakers = ["Akhilesh Shukla", "Bhanu Bhatia", "Rick Arora", "Bhanu", "Akhilesh", "Automation"];
        
        if (q || kw) {
            dialogueList = dialogueList.filter(turn => {
                const textLower = turn.text.toLowerCase();
                const speakerLower = turn.speaker.toLowerCase();
                
                let matchesSearch = true;
                if (q) {
                    matchesSearch = textLower.includes(q) || speakerLower.includes(q);
                }
                
                let matchesKeyword = true;
                if (kw) {
                    if (kw === "sla") {
                        matchesKeyword = textLower.includes("sla") || textLower.includes("response time") || textLower.includes("target");
                    } else if (kw === "pip_sip") {
                        matchesKeyword = textLower.includes("pip") || textLower.includes("sip") || textLower.includes("monitoring") || textLower.includes("plan");
                    } else if (kw === "unreliability") {
                        matchesKeyword = textLower.includes("absent") || textLower.includes("attendance") || textLower.includes("unreliable") || textLower.includes("replace") || textLower.includes("unplanned");
                    } else if (kw === "improvement") {
                        matchesKeyword = textLower.includes("coaching") || textLower.includes("improve") || textLower.includes("training") || textLower.includes("progress") || textLower.includes("success");
                    }
                }
                
                return matchesSearch && matchesKeyword;
            });
        }
        
        if (dialogueList.length === 0) {
            elements.dialogueStream.innerHTML = `<div class="no-results">No dialogue matches found for your filter/search criteria.</div>`;
            return;
        }
        
        dialogueList.forEach(turn => {
            const tr = document.createElement("div");
            
            const isItbd = itbdSpeakers.some(s => turn.speaker.includes(s));
            tr.className = `dialogue-turn ${isItbd ? 'itbd' : 'client'}`;
            
            // Highlight matching text in chat bubble
            let text = turn.text;
            
            // Highlight terms
            // Risks: PIP, SIP, SLA, absent, attendance, unreliability, mistake, avoided, uncompleted
            const riskRegex = /\b(pip|sip|sla|absent|attendance|unreliable|unreliability|mistake|mistakes|avoiding|missed)\b/gi;
            text = text.replace(riskRegex, match => `<span class="highlight-risk">${match}</span>`);
            
            // Improvements: improvement, coaching, training, completed, closed, correct, success, positive
            const improveRegex = /\b(improvement|coaching|training|completed|closed|correct|success|positive|improved)\b/gi;
            text = text.replace(improveRegex, match => `<span class="highlight-itbd">${match}</span>`);
            
            tr.innerHTML = `
                <div class="turn-meta">
                    <span class="turn-speaker">${turn.speaker}</span>
                    <span class="turn-time">${turn.timestamp}</span>
                </div>
                <div class="turn-bubble">${text}</div>
            `;
            elements.dialogueStream.appendChild(tr);
        });
    }

    // Initialize Page
    function init() {
        setupNavigation();
        initClientMeta();
        renderOverview();
        renderActionsPage();
        setupFeedbackPage();
        renderFeedbackGrid();
        initTranscriptsPage();
        renderTranscriptDialogue();
    }

    init();
});
