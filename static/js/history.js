// static/js/history.js
document.addEventListener('DOMContentLoaded', function() {
    let currentPage = 1;
    let perPage = 20;
    let loading = false;
    let hasMore = true;
    let filters = {};

    const timelineList = document.getElementById('timelineList');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const filterType = document.getElementById('filterType');
    const filterStartDate = document.getElementById('filterStartDate');
    const filterEndDate = document.getElementById('filterEndDate');
    const filterSearch = document.getElementById('filterSearch');

    // Load initial stats
    fetchStats();

    // Load first page
    loadEntries(true);

    // Event listeners for filters (debounced)
    let debounceTimer;
    function applyFilters() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            currentPage = 1;
            hasMore = true;
            timelineList.innerHTML = '';
            loadEntries(true);
        }, 400);
    }

    filterType.addEventListener('change', applyFilters);
    filterStartDate.addEventListener('change', applyFilters);
    filterEndDate.addEventListener('change', applyFilters);
    filterSearch.addEventListener('input', applyFilters);

    // Load more
    window.loadMore = function() {
        if (!loading && hasMore) {
            loadEntries(false);
        }
    };

    // Export
    window.exportHistory = function() {
        const params = buildParams();
        window.location.href = '/history/api/export?' + params;
    };

    function buildParams() {
        const params = new URLSearchParams();
        const types = Array.from(filterType.selectedOptions).map(opt => opt.value).filter(v => v);
        if (types.length) params.set('types', types.join(','));
        if (filterStartDate.value) params.set('start_date', filterStartDate.value);
        if (filterEndDate.value) params.set('end_date', filterEndDate.value);
        if (filterSearch.value) params.set('search', filterSearch.value);
        return params.toString();
    }

    function loadEntries(reset) {
        if (loading) return;
        loading = true;
        if (reset) {
            currentPage = 1;
            hasMore = true;
        }

        const params = buildParams();
        params.set('page', currentPage);
        params.set('per_page', perPage);

        fetch('/history/api/entries?' + params.toString())
            .then(res => res.json())
            .then(data => {
                loading = false;
                if (data.error) {
                    console.error(data.error);
                    return;
                }

                const entries = data.entries;
                if (reset) {
                    timelineList.innerHTML = '';
                }

                if (entries.length === 0 && reset) {
                    timelineList.innerHTML = `
                        <div class="history-empty">
                            <div class="icon">📭</div>
                            <p>No history entries found.</p>
                        </div>
                    `;
                    loadMoreBtn.style.display = 'none';
                    hasMore = false;
                    return;
                }

                // Group by date
                const groups = {};
                entries.forEach(entry => {
                    const date = entry.created_at.split('T')[0];
                    if (!groups[date]) groups[date] = [];
                    groups[date].push(entry);
                });

                let html = '';
                for (const [date, items] of Object.entries(groups)) {
                    html += `<div class="history-day-group"><div class="day-label">${formatDate(date)}</div>`;
                    items.forEach(item => {
                        html += renderEntry(item);
                    });
                    html += '</div>';
                }

                if (reset) {
                    timelineList.innerHTML = html;
                } else {
                    timelineList.insertAdjacentHTML('beforeend', html);
                }

                // Pagination
                const total = data.pagination.total;
                const pages = data.pagination.pages;
                if (currentPage < pages) {
                    loadMoreBtn.style.display = 'block';
                    hasMore = true;
                } else {
                    loadMoreBtn.style.display = 'none';
                    hasMore = false;
                }
                currentPage++;
            })
            .catch(err => {
                console.error(err);
                loading = false;
            });
    }

    function renderEntry(entry) {
        const iconMap = {
            'quiz_attempt': '✅',
            'live_quiz': '⚡',
            'achievement': '🏆',
            'save': '💾',
            'pdf_view': '📄',
            'pdf_download': '⬇️',
            'like': '❤️',
            'report': '⚠️'
        };
        const icon = iconMap[entry.entry_type] || '📌';

        let title = entry.entry_type.replace('_', ' ');
        let meta = '';
        let timeAgo = getTimeAgo(entry.created_at);

        if (entry.entry_type === 'quiz_attempt') {
            try {
                const metaData = JSON.parse(entry.metadata);
                const subject = metaData.subject || 'Unknown';
                const score = metaData.score || 0;
                const total = metaData.total || 0;
                const pct = metaData.percentage || 0;
                title = `${subject} Quiz`;
                meta = `Score: ${score}/${total} (${pct}%)`;
            } catch(e) {
                title = 'Quiz Attempt';
            }
        } else if (entry.entry_type === 'live_quiz') {
            try {
                const metaData = JSON.parse(entry.metadata);
                const subject = metaData.subject || 'Unknown';
                const rank = metaData.rank || '-';
                title = `Live Quiz: ${subject}`;
                meta = `Rank: #${rank}`;
            } catch(e) {
                title = 'Live Quiz';
            }
        } else if (entry.entry_type === 'achievement') {
            try {
                const metaData = JSON.parse(entry.metadata);
                const name = metaData.name || 'Achievement';
                title = `Unlocked: ${name}`;
                meta = metaData.icon || '';
            } catch(e) {
                title = 'Achievement Unlocked';
            }
        } else if (entry.entry_type === 'save') {
            try {
                const metaData = JSON.parse(entry.metadata);
                const content = metaData.content_type || 'item';
                title = `Saved ${content}`;
            } catch(e) {
                title = 'Saved item';
            }
        } else if (entry.entry_type === 'pdf_view') {
            try {
                const metaData = JSON.parse(entry.metadata);
                const pdfTitle = metaData.title || 'PDF';
                title = `Viewed: ${pdfTitle}`;
            } catch(e) {
                title = 'Viewed PDF';
            }
        } else if (entry.entry_type === 'pdf_download') {
            try {
                const metaData = JSON.parse(entry.metadata);
                const pdfTitle = metaData.title || 'PDF';
                title = `Downloaded: ${pdfTitle}`;
            } catch(e) {
                title = 'Downloaded PDF';
            }
        } else if (entry.entry_type === 'like') {
            title = entry.action === 'liked' ? '❤️ Liked a question' : '💔 Unliked a question';
        } else if (entry.entry_type === 'report') {
            title = '⚠️ Reported a question';
        } else {
            title = entry.action.charAt(0).toUpperCase() + entry.action.slice(1) + ' ' + entry.entry_type;
        }

        return `
            <div class="history-entry">
                <span class="entry-icon">${icon}</span>
                <div class="entry-content">
                    <div class="entry-title">${title}</div>
                    ${meta ? `<div class="entry-meta">${meta}</div>` : ''}
                </div>
                <div class="entry-time">${timeAgo}</div>
            </div>
        `;
    }

    function formatDate(dateStr) {
        const today = new Date().toISOString().split('T')[0];
        const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
        if (dateStr === today) return 'Today';
        if (dateStr === yesterday) return 'Yesterday';
        return dateStr;
    }

    function getTimeAgo(isoDate) {
        const diff = (Date.now() - new Date(isoDate).getTime()) / 1000;
        if (diff < 60) return 'Just now';
        if (diff < 3600) return Math.floor(diff/60) + 'm ago';
        if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
        if (diff < 604800) return Math.floor(diff/86400) + 'd ago';
        return new Date(isoDate).toLocaleDateString();
    }

    function fetchStats() {
        fetch('/history/api/stats')
            .then(res => res.json())
            .then(data => {
                document.getElementById('statTotal').textContent = data.total || 0;
                document.getElementById('statQuizzes').textContent = data.quizzes || 0;
                document.getElementById('statAchievements').textContent = data.achievements || 0;
                document.getElementById('statSaves').textContent = data.saves || 0;
                document.getElementById('statAvgScore').textContent = (data.avg_score || 0) + '%';
            })
            .catch(err => console.error(err));
    }
});