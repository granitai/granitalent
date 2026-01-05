const API_BASE_URL = 'http://localhost:8000';
let allJobs = [];
let filteredJobs = [];

// DOM Elements
const searchInput = document.getElementById('searchInput');
const jobsList = document.getElementById('jobsList');
const applicationModal = document.getElementById('applicationModal');
const applicationForm = document.getElementById('applicationForm');
const closeModal = document.getElementById('closeModal');
const cancelBtn = document.getElementById('cancelBtn');
const cvUploadArea = document.getElementById('cvUploadArea');
const cvFileInput = document.getElementById('cvFileInput');
const selectedFile = document.getElementById('selectedFile');
const successMessage = document.getElementById('successMessage');

// Load jobs on page load
document.addEventListener('DOMContentLoaded', () => {
    loadJobOffers();
    setupEventListeners();
});

function setupEventListeners() {
    searchInput.addEventListener('input', handleSearch);
    closeModal.addEventListener('click', closeApplicationModal);
    cancelBtn.addEventListener('click', closeApplicationModal);
    applicationModal.addEventListener('click', (e) => {
        if (e.target === applicationModal) closeApplicationModal();
    });
    applicationForm.addEventListener('submit', handleApplicationSubmit);
    
    // File upload
    cvUploadArea.addEventListener('click', () => cvFileInput.click());
    cvUploadArea.addEventListener('dragover', handleDragOver);
    cvUploadArea.addEventListener('drop', handleDrop);
    cvFileInput.addEventListener('change', handleFileSelect);
}

async function loadJobOffers() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/job-offers`);
        if (!response.ok) throw new Error('Failed to load job offers');
        
        allJobs = await response.json();
        filteredJobs = allJobs;
        renderJobs();
        extractFilters();
    } catch (error) {
        jobsList.innerHTML = `
            <div class="loading-state">
                <p style="color: var(--error);">Error loading job offers. Please try again later.</p>
            </div>
        `;
        console.error('Error loading jobs:', error);
    }
}

function renderJobs() {
    if (filteredJobs.length === 0) {
        jobsList.innerHTML = `
            <div class="loading-state">
                <p>No job offers found matching your search.</p>
            </div>
        `;
        return;
    }
    
    jobsList.innerHTML = filteredJobs.map(job => `
        <div class="job-card" onclick="openApplicationModal('${job.offer_id}')">
            <div class="job-card-header">
                <h3 class="job-title">${escapeHtml(job.title)}</h3>
                <div class="job-meta">
                    ${job.experience_level ? `<span class="job-meta-item">📊 ${escapeHtml(job.experience_level)}</span>` : ''}
                    <span class="job-meta-item">📅 ${formatDate(job.created_at)}</span>
                </div>
            </div>
            <p class="job-description">${escapeHtml(job.description)}</p>
            ${job.required_skills ? `
                <div class="job-skills">
                    ${job.required_skills.split(',').slice(0, 5).map(skill => `
                        <span class="skill-tag">${escapeHtml(skill.trim())}</span>
                    `).join('')}
                </div>
            ` : ''}
            <div class="job-card-footer">
                <button class="apply-btn" onclick="event.stopPropagation(); openApplicationModal('${job.offer_id}')">
                    Apply Now →
                </button>
            </div>
        </div>
    `).join('');
}

function extractFilters() {
    const filters = new Set();
    allJobs.forEach(job => {
        if (job.experience_level) filters.add(job.experience_level);
        if (job.required_skills) {
            job.required_skills.split(',').forEach(skill => {
                if (skill.trim()) filters.add(skill.trim());
            });
        }
    });
    
    const filterTags = document.getElementById('filterTags');
    filterTags.innerHTML = Array.from(filters).slice(0, 8).map(filter => `
        <span class="filter-tag" onclick="toggleFilter('${escapeHtml(filter)}')">${escapeHtml(filter)}</span>
    `).join('');
}

let activeFilters = [];

function toggleFilter(filter) {
    const index = activeFilters.indexOf(filter);
    if (index > -1) {
        activeFilters.splice(index, 1);
    } else {
        activeFilters.push(filter);
    }
    
    // Update UI
    document.querySelectorAll('.filter-tag').forEach(tag => {
        if (tag.textContent === filter) {
            tag.classList.toggle('active');
        }
    });
    
    applyFilters();
}

function handleSearch() {
    applyFilters();
}

function applyFilters() {
    const searchTerm = searchInput.value.toLowerCase();
    
    filteredJobs = allJobs.filter(job => {
        const matchesSearch = !searchTerm || 
            job.title.toLowerCase().includes(searchTerm) ||
            job.description.toLowerCase().includes(searchTerm) ||
            (job.required_skills && job.required_skills.toLowerCase().includes(searchTerm));
        
        const matchesFilters = activeFilters.length === 0 || 
            activeFilters.some(filter => 
                (job.experience_level && job.experience_level.includes(filter)) ||
                (job.required_skills && job.required_skills.includes(filter))
            );
        
        return matchesSearch && matchesFilters;
    });
    
    renderJobs();
}

function openApplicationModal(jobId) {
    const job = allJobs.find(j => j.offer_id === jobId);
    if (!job) return;
    
    document.getElementById('selectedJobId').value = jobId;
    document.querySelector('.modal-header h2').textContent = `Apply for ${job.title}`;
    applicationModal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeApplicationModal() {
    applicationModal.classList.remove('active');
    document.body.style.overflow = '';
    applicationForm.reset();
    selectedFile.style.display = 'none';
    cvUploadArea.style.display = 'block';
}

function handleDragOver(e) {
    e.preventDefault();
    cvUploadArea.style.borderColor = 'var(--primary)';
    cvUploadArea.style.background = 'var(--primary-light)';
}

function handleDrop(e) {
    e.preventDefault();
    cvUploadArea.style.borderColor = 'var(--border)';
    cvUploadArea.style.background = 'var(--bg-secondary)';
    
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type === 'application/pdf') {
        cvFileInput.files = files;
        handleFileSelect();
    }
}

function handleFileSelect() {
    const file = cvFileInput.files[0];
    if (file) {
        selectedFile.innerHTML = `
            <span>📄 ${escapeHtml(file.name)} (${(file.size / 1024 / 1024).toFixed(2)} MB)</span>
            <button type="button" onclick="clearFile()" style="background: none; border: none; color: var(--error); cursor: pointer;">✕</button>
        `;
        selectedFile.style.display = 'flex';
        cvUploadArea.style.display = 'none';
    }
}

function clearFile() {
    cvFileInput.value = '';
    selectedFile.style.display = 'none';
    cvUploadArea.style.display = 'block';
}

async function handleApplicationSubmit(e) {
    e.preventDefault();
    
    const formData = new FormData();
    formData.append('job_offer_id', document.getElementById('selectedJobId').value);
    formData.append('full_name', document.getElementById('fullName').value);
    formData.append('email', document.getElementById('email').value);
    formData.append('phone', document.getElementById('phone').value);
    formData.append('linkedin', document.getElementById('linkedin').value || '');
    formData.append('portfolio', document.getElementById('portfolio').value || '');
    formData.append('cover_letter', document.getElementById('coverLetter').value || '');
    formData.append('cv_file', cvFileInput.files[0]);
    
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const submitText = document.getElementById('submitText');
    const submitLoader = document.getElementById('submitLoader');
    
    submitBtn.disabled = true;
    submitText.style.display = 'none';
    submitLoader.style.display = 'inline-block';
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/candidates/apply`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to submit application');
        }
        
        const result = await response.json();
        
        // Show success message
        successMessage.classList.add('show');
        setTimeout(() => {
            successMessage.classList.remove('show');
        }, 3000);
        
        // Close modal and reset form
        closeApplicationModal();
        
    } catch (error) {
        alert('Error submitting application: ' + error.message);
    } finally {
        submitBtn.disabled = false;
        submitText.style.display = 'inline';
        submitLoader.style.display = 'none';
    }
}

function formatDate(dateString) {
    if (!dateString) return 'Recently';
    try {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return 'Recently';
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch (e) {
        return 'Recently';
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Make functions global for onclick handlers
window.openApplicationModal = openApplicationModal;
window.toggleFilter = toggleFilter;
window.clearFile = clearFile;

