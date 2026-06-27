// ------------------ GLOBAL CONFIGURATION & STATE ------------------
const API_URL = "http://157.245.98.15:8000";

let currentUser = null;
let currentToken = null;
let classes = [];
let subjects = [];

// Session state
let activeSessionId = null;
let sessionTimerInterval = null;
let sessionStartTime = null;
let detectionLoopInterval = null;
let isCaptureLoopRunning = false;

// Media streams
let activeStream = null;
let enrollStream = null;
let editStream = null;
let editCapturedImageBase64 = null;

// Roster state
let presentStudents = new Set(); // Stores PRN of present students
let studentDetails = {}; // PRN -> { name, roll_no, last_seen }

// ------------------ DOM ELEMENT REFERENCES ------------------
const loginContainer = document.getElementById("login-container");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const appContainer = document.getElementById("app-container");

const navItems = document.querySelectorAll(".nav-item");
const tabPanes = document.querySelectorAll(".tab-pane");
const pageTitle = document.getElementById("page-title");
const pageSubtitle = document.getElementById("page-subtitle");
const currentTimeLabel = document.getElementById("current-time");

const userNameLabel = document.getElementById("user-name");
const userRoleLabel = document.getElementById("user-role");
const logoutBtn = document.getElementById("logout-btn");

// Session Panel Elements
const classSelect = document.getElementById("class-select");
const subjectSelect = document.getElementById("subject-select");
const cameraSelect = document.getElementById("camera-select");
const startSessionBtn = document.getElementById("start-session-btn");
const endSessionBtn = document.getElementById("end-session-btn");
const sessionStatusBadge = document.getElementById("session-status-badge");
const videoPlaceholder = document.getElementById("video-placeholder");

const webcam = document.getElementById("webcam");
const canvasOverlay = document.getElementById("canvas-overlay");
const ctxOverlay = canvasOverlay.getContext("2d");

// Stats Elements
const statTotalStudents = document.getElementById("stat-total-students");
const statPresentCount = document.getElementById("stat-present-count");
const statElapsedTime = document.getElementById("stat-elapsed-time");
const liveRosterBody = document.getElementById("live-roster-body");
const rosterCountBadge = document.getElementById("roster-count-badge");

// Enrollment Panel Elements
const enrollForm = document.getElementById("enrollment-form");
const enrollClassSelect = document.getElementById("enroll-class");
const enrollVideo = document.getElementById("enroll-video");
const enrollCanvas = document.getElementById("enroll-canvas");
const capturedImg = document.getElementById("captured-img");
const btnCapture = document.getElementById("btn-capture");
const btnRetake = document.getElementById("btn-retake");
const qualityAlert = document.getElementById("quality-alert");
const qualityMsg = document.getElementById("quality-msg");
const btnSubmitEnroll = document.getElementById("btn-submit-enroll");

// Results Modal Elements
const resultsModal = document.getElementById("results-modal");
const resultsTbody = document.getElementById("results-tbody");
const btnDownloadCsv = document.getElementById("btn-download-csv");
const resTotalReg = document.getElementById("res-total-reg");
const resTotalPresent = document.getElementById("res-total-present");
const btnCloseModal = document.getElementById("close-modal");

// Logs/Reports Elements
const reportSearch = document.getElementById("report-search");

// Semester Select Elements
const semesterSelect = document.getElementById("semester-select");

// Manage Students Elements
const studentListBody = document.getElementById("student-list-body");
const studentSearch = document.getElementById("student-search");

// Edit Student Modal Elements
const editStudentModal = document.getElementById("edit-student-modal");
const closeEditModal = document.getElementById("close-edit-modal");
const editForm = document.getElementById("edit-student-form");
const editPrnInput = document.getElementById("edit-prn");
const editClassSelect = document.getElementById("edit-class");
const editNameInput = document.getElementById("edit-name");
const editRollInput = document.getElementById("edit-roll");
const editEmailInput = document.getElementById("edit-email");

const editVideo = document.getElementById("edit-video");
const editCanvas = document.getElementById("edit-canvas");
const editCapturedImg = document.getElementById("edit-captured-img");
const btnEditActivateCam = document.getElementById("btn-edit-activate-cam");
const btnEditCapture = document.getElementById("btn-edit-capture");
const btnEditRetake = document.getElementById("btn-edit-retake");
const editPhotoPlaceholder = document.getElementById("edit-photo-placeholder");
const editQualityAlert = document.getElementById("edit-quality-alert");
const editQualityMsg = document.getElementById("edit-quality-msg");
const btnSubmitEdit = document.getElementById("btn-submit-edit");

// ------------------ INITIALIZATION ------------------
document.addEventListener("DOMContentLoaded", () => {
    // Run clock
    setInterval(updateClock, 1000);
    updateClock();

    // Login Form Submission
    loginForm.addEventListener("submit", handleLogin);
    
    // Tab switching
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-target");
            switchTab(targetTab);
        });
    });

    // Session buttons
    startSessionBtn.addEventListener("click", startSession);
    endSessionBtn.addEventListener("click", endSession);
    
    // Enrollment Capture flow
    btnCapture.addEventListener("click", captureEnrollPhoto);
    btnRetake.addEventListener("click", retakeEnrollPhoto);
    enrollForm.addEventListener("submit", submitEnrollment);

    // Close Modal
    btnCloseModal.addEventListener("click", () => resultsModal.classList.remove("active"));
    
    // Search logs
    reportSearch.addEventListener("input", filterLogs);

    // Logs report page elements event listeners
    const reportSessionSelect = document.getElementById("report-session-select");
    const btnExportLogCsv = document.getElementById("btn-export-log-csv");
    if (reportSessionSelect) {
        reportSessionSelect.addEventListener("change", renderLogsReportTable);
    }
    if (btnExportLogCsv) {
        btnExportLogCsv.addEventListener("click", exportReportToCSV);
    }

    // Logout
    logoutBtn.addEventListener("click", handleLogout);

    // Dynamic subjects update by Semester
    if (semesterSelect) {
        semesterSelect.addEventListener("change", populateSubjectsFiltered);
    }

    // Student Search in Management Directory
    if (studentSearch) {
        studentSearch.addEventListener("input", filterStudents);
    }

    // Edit Modal bindings
    if (closeEditModal) {
        closeEditModal.addEventListener("click", () => {
            editStudentModal.classList.remove("active");
            editStudentModal.classList.add("hide");
            stopEditWebcam();
        });
    }
    if (editForm) {
        editForm.addEventListener("submit", submitEditStudent);
    }
    if (btnEditActivateCam) {
        btnEditActivateCam.addEventListener("click", startEditWebcam);
    }
    if (btnEditCapture) {
        btnEditCapture.addEventListener("click", captureEditPhoto);
    }
    if (btnEditRetake) {
        btnEditRetake.addEventListener("click", retakeEditPhoto);
    }

    // Check active session on page load
    checkActiveSessionOnLoad();

    // Image uploads
    const enrollFileInput = document.getElementById("enroll-file-input");
    if (enrollFileInput) {
        enrollFileInput.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = function(evt) {
                const base64Data = evt.target.result;
                stopEnrollWebcam();
                capturedImg.src = base64Data;
                enrollVideo.classList.add("hide");
                capturedImg.classList.remove("hide");
                btnCapture.classList.add("hide");
                btnRetake.classList.remove("hide");
                validateCapturedFace(base64Data);
            };
            reader.readAsDataURL(file);
        });
    }
    
    const editFileInput = document.getElementById("edit-file-input");
    if (editFileInput) {
        editFileInput.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = function(evt) {
                const base64Data = evt.target.result;
                stopEditWebcam();
                editCapturedImageBase64 = base64Data;
                editCapturedImg.src = base64Data;
                editCapturedImg.classList.remove("hide");
                editVideo.classList.add("hide");
                if (btnEditCapture) btnEditCapture.classList.add("hide");
                if (btnEditRetake) btnEditRetake.classList.remove("hide");
                if (editPhotoPlaceholder) editPhotoPlaceholder.classList.add("hide");
                validateEditFace(base64Data);
            };
            reader.readAsDataURL(file);
        });
    }

    // Bulk CSV Enrollment submit
    const bulkEnrollForm = document.getElementById("bulk-enroll-form");
    const bulkEnrollFile = document.getElementById("bulk-enroll-file");
    const bulkImportResult = document.getElementById("bulk-import-result");
    
    if (bulkEnrollForm) {
        bulkEnrollForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!bulkEnrollFile.files || bulkEnrollFile.files.length === 0) {
                alert("Please select a CSV file to upload.");
                return;
            }
            
            const file = bulkEnrollFile.files[0];
            const formData = new FormData();
            formData.append("file", file);
            
            bulkImportResult.classList.remove("hide");
            bulkImportResult.className = "alert-box info";
            bulkImportResult.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Uploading and importing student records...`;
            
            try {
                const response = await fetch(`${API_URL}/api/students/bulk-import`, {
                    method: "POST",
                    body: formData
                });
                
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || "Import failed");
                
                let resultMsg = `<i class="fa-solid fa-circle-check"></i> Bulk Import Complete! Successfully imported <strong>${data.imported_count}</strong> students.`;
                if (data.errors && data.errors.length > 0) {
                    resultMsg += `<br><br><strong>Errors encountered (${data.errors.length}):</strong><ul style="margin-left: 20px; font-size: 0.85rem; max-height: 100px; overflow-y: auto;">`;
                    data.errors.forEach(err => {
                        resultMsg += `<li>${err}</li>`;
                    });
                    resultMsg += `</ul>`;
                }
                
                bulkImportResult.className = "alert-box success";
                bulkImportResult.innerHTML = resultMsg;
                bulkEnrollForm.reset();
                loadEnrolledStudents();
            } catch(err) {
                bulkImportResult.className = "alert-box error";
                bulkImportResult.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Import failed: ${err.message}`;
            }
        });
    }
});

function updateClock() {
    const now = new Date();
    currentTimeLabel.textContent = now.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true
    });
}

// ------------------ AUTHENTICATION FLOW ------------------
async function handleLogin(e) {
    e.preventDefault();
    loginError.classList.add("hide");

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    try {
        const response = await fetch(`${API_URL}/api/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Login failed");
        }

        const data = await response.json();
        currentUser = { username: data.username, name: data.name, role: data.role };
        currentToken = data.token;

        // Save session locally
        localStorage.setItem("user", JSON.stringify(currentUser));
        localStorage.setItem("token", currentToken);

        setupUserInterface(currentUser);
        loginContainer.classList.remove("active");
        appContainer.classList.remove("hide");

        // Load application data
        loadApplicationData();

        // Redirect to role-based default tab
        if (currentUser.role === "admin") {
            switchTab("enroll-tab");
        } else {
            switchTab("session-tab");
        }
    } catch (error) {
        loginError.classList.remove("hide");
        loginError.innerHTML = `<i class="fa-solid fa-circle-exclamation"></i> ${error.message}`;
    }
}

function handleLogout() {
    localStorage.removeItem("user");
    localStorage.removeItem("token");
    
    // Stop all media streams
    stopWebcam();
    stopEnrollWebcam();
    
    currentUser = null;
    currentToken = null;
    
    appContainer.classList.add("hide");
    loginContainer.classList.add("active");
}

function setupUserInterface(user) {
    userNameLabel.textContent = user.name;
    userRoleLabel.textContent = user.role;

    // Manage role-based UI options
    const adminElements = document.querySelectorAll(".admin-only");
    adminElements.forEach(el => {
        if (user.role === "admin") {
            el.classList.remove("hide");
        } else {
            el.classList.add("hide");
        }
    });

    const teacherElements = document.querySelectorAll(".teacher-only");
    teacherElements.forEach(el => {
        if (user.role === "teacher") {
            el.classList.remove("hide");
        } else {
            el.classList.add("hide");
        }
    });
}

function checkActiveSessionOnLoad() {
    const savedUser = localStorage.getItem("user");
    const savedToken = localStorage.getItem("token");

    if (savedUser && savedToken) {
        currentUser = JSON.parse(savedUser);
        currentToken = savedToken;
        setupUserInterface(currentUser);
        loginContainer.classList.remove("active");
        appContainer.classList.remove("hide");
        
        loadApplicationData();
        checkActiveSessionBackend();

        // Redirect to role-based default tab on load
        if (currentUser.role === "admin") {
            switchTab("enroll-tab");
        } else {
            switchTab("session-tab");
        }
    }
}

// ------------------ DATA LOADING ------------------
async function loadApplicationData() {
    try {
        // Fetch classrooms
        const resClasses = await fetch(`${API_URL}/api/classes`);
        classes = await resClasses.json();
        
        // Fetch subjects (detailed)
        const resSubjects = await fetch(`${API_URL}/api/subjects`);
        subjects = await resSubjects.json();

        // Populate dropdowns
        classSelect.innerHTML = `<option value="">Select Class...</option>`;
        enrollClassSelect.innerHTML = `<option value="">Select Class...</option>`;
        
        // Populate edit class dropdown
        if (editClassSelect) {
            editClassSelect.innerHTML = `<option value="">Select Class...</option>`;
        }

        classes.forEach(c => {
            const opt = `<option value="${c.id}">${c.name}</option>`;
            classSelect.insertAdjacentHTML("beforeend", opt);
            enrollClassSelect.insertAdjacentHTML("beforeend", opt);
            if (editClassSelect) {
                editClassSelect.insertAdjacentHTML("beforeend", opt);
            }
        });

        // Initialize subjects empty or default instruction
        subjectSelect.innerHTML = `<option value="">Select Semester First...</option>`;

        // Initialize camera list
        await initCameraDevices();
        
        // Fetch recent logs
        fetchSystemLogs();
    } catch (e) {
        console.error("Failed to load backend lists", e);
    }
}

async function initCameraDevices() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(device => device.kind === 'videoinput');
        
        cameraSelect.innerHTML = "";
        videoDevices.forEach((device, index) => {
            const option = document.createElement("option");
            option.value = device.deviceId;
            option.text = device.label || `Camera ${index + 1}`;
            cameraSelect.appendChild(option);
        });
    } catch (e) {
        console.error("Camera listing failed", e);
    }
}

// ------------------ NAVIGATION & TABS ------------------
function switchTab(tabId) {
    navItems.forEach(item => {
        if (item.getAttribute("data-target") === tabId) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });

    tabPanes.forEach(pane => {
        if (pane.id === tabId) {
            pane.classList.add("active");
        } else {
            pane.classList.remove("active");
        }
    });

    // Handle tab transitions/events
    if (tabId === "enroll-tab") {
        pageTitle.textContent = "Student Face Enrollment";
        pageSubtitle.textContent = "Register a new profile by extracting high-quality face embeddings";
        startEnrollWebcam();
    } else {
        stopEnrollWebcam();
    }

    if (tabId === "session-tab") {
        pageTitle.textContent = "Classroom Session Tracking";
        pageSubtitle.textContent = "Real-time attendance scanning & presence calculation";
    }

    if (tabId === "manage-tab") {
        pageTitle.textContent = "Manage Enrolled Students";
        pageSubtitle.textContent = "View, edit, or delete registered student profiles and biometric data";
        loadEnrolledStudents();
    }

    if (tabId === "logs-tab") {
        pageTitle.textContent = "Attendance Log Archives";
        pageSubtitle.textContent = "Review historic attendance registers and student enrollment records";
        fetchSystemLogs();
    }

    if (tabId === "analytics-tab") {
        pageTitle.textContent = "Attendance Analytics & Insights";
        pageSubtitle.textContent = "Class comparison and session tracking trends";
        initAnalyticsTab();
    }

    if (tabId === "chat-tab") {
        pageTitle.textContent = "AI Assistant";
        pageSubtitle.textContent = "Ask questions in plain English to query the database";
        initChatTab();
    }
}

// ------------------ CAMERA / CAPTURE CORE ------------------
async function startWebcam() {
    try {
        const deviceId = cameraSelect.value;
        const constraints = {
            video: deviceId ? { deviceId: { exact: deviceId } } : true
        };
        
        activeStream = await navigator.mediaDevices.getUserMedia(constraints);
        webcam.srcObject = activeStream;
        videoPlaceholder.classList.add("hide");
        webcam.classList.remove("hide");
    } catch (error) {
        console.error("Failed to acquire webcam stream", error);
        alert("Unable to open camera. Please verify camera permissions.");
    }
}

function stopWebcam() {
    if (activeStream) {
        activeStream.getTracks().forEach(track => track.stop());
        activeStream = null;
    }
    webcam.srcObject = null;
    webcam.classList.add("hide");
    videoPlaceholder.classList.remove("hide");
    
    // Clear overlay canvas
    ctxOverlay.clearRect(0, 0, canvasOverlay.width, canvasOverlay.height);
}

// ------------------ SESSION WORKFLOWS ------------------
async function checkActiveSessionBackend() {
    try {
        const res = await fetch(`${API_URL}/api/sessions/active`);
        const session = await res.json();
        
        if (session.session_id) {
            // Restore session
            activeSessionId = session.session_id;
            sessionStartTime = new Date(session.start_time);
            
            // Set selections
            classSelect.value = session.class_id;
            subjectSelect.value = session.subject_id;
            
            // Lock controls
            classSelect.disabled = true;
            subjectSelect.disabled = true;
            cameraSelect.disabled = true;
            
            // Start local UI streams & capture loop
            startSessionBtn.classList.add("hide");
            endSessionBtn.classList.remove("hide");
            sessionStatusBadge.textContent = `Active (ID: ${activeSessionId})`;
            sessionStatusBadge.classList.add("active");
            
            await startWebcam();
            startCaptureLoop();
            startTimer();
            fetchClassroomStats(session.class_id);
        }
    } catch (e) {
        console.error(e);
    }
}

async function startSession() {
    const classId = classSelect.value;
    const subjectId = subjectSelect.value;

    if (!classId || !subjectId) {
        alert("Please select both a classroom and subject first.");
        return;
    }

    try {
        const response = await fetch(`${API_URL}/api/sessions/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ class_id: parseInt(classId), subject_id: parseInt(subjectId) })
        });

        const data = await response.json();
        if (!data.success) throw new Error(data.detail);

        activeSessionId = data.session_id;
        sessionStartTime = new Date();
        
        // UI updates
        classSelect.disabled = true;
        subjectSelect.disabled = true;
        cameraSelect.disabled = true;
        startSessionBtn.classList.add("hide");
        endSessionBtn.classList.remove("hide");
        sessionStatusBadge.textContent = `Active (ID: ${activeSessionId})`;
        sessionStatusBadge.classList.add("active");

        // Start webcam and frame scanning
        await startWebcam();
        startCaptureLoop();
        startTimer();
        
        // Reset statistics
        presentStudents.clear();
        studentDetails = {};
        updateLiveRosterUI();
        fetchClassroomStats(classId);
    } catch (e) {
        alert("Failed to start class session: " + e.message);
    }
}

async function endSession() {
    if (!activeSessionId) return;

    if (!confirm("Are you sure you want to end this classroom session and compute attendance?")) {
        return;
    }

    // Stop session components immediately to prevent further frame requests
    stopCaptureLoop();
    stopWebcam();
    stopTimer();

    try {
        const response = await fetch(`${API_URL}/api/sessions/${activeSessionId}/end`, {
            method: "POST"
        });

        const data = await response.json();
        if (!data.success) throw new Error(data.detail);

        // Release dropdown locks
        classSelect.disabled = false;
        subjectSelect.disabled = false;
        cameraSelect.disabled = false;
        startSessionBtn.classList.remove("hide");
        endSessionBtn.classList.add("hide");
        sessionStatusBadge.textContent = "Inactive";
        sessionStatusBadge.classList.remove("active");

        activeSessionId = null;

        // Display results modal
        showSessionResults(data.results);
    } catch (e) {
        alert("Failed to end session: " + e.message);
    }
}

function startTimer() {
    clearInterval(sessionTimerInterval);
    sessionTimerInterval = setInterval(() => {
        if (!sessionStartTime) return;
        const diff = Math.floor((new Date() - sessionStartTime) / 1000);
        const hours = String(Math.floor(diff / 3600)).padStart(2, '0');
        const mins = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
        const secs = String(diff % 60).padStart(2, '0');
        statElapsedTime.textContent = `${hours}:${mins}:${secs}`;
    }, 1000);
}

function stopTimer() {
    clearInterval(sessionTimerInterval);
    statElapsedTime.textContent = "00:00:00";
}

async function fetchClassroomStats(classId) {
    try {
        const res = await fetch(`${API_URL}/api/students`);
        const students = await res.json();
        const classroomTotal = students.filter(s => s.class_id === parseInt(classId)).length;
        statTotalStudents.textContent = classroomTotal;
    } catch (e) {
        console.error(e);
    }
}

// ------------------ RUNTIME CAPTURE / DETECTION LOOP ------------------
function startCaptureLoop() {
    isCaptureLoopRunning = true;
    scheduleNextFrame();
}

function stopCaptureLoop() {
    isCaptureLoopRunning = false;
    // Clear overlay canvas
    ctxOverlay.clearRect(0, 0, canvasOverlay.width, canvasOverlay.height);
}

async function scheduleNextFrame() {
    if (!isCaptureLoopRunning) return;
    await processWebcamFrame();
    if (isCaptureLoopRunning) {
        setTimeout(scheduleNextFrame, 1000);
    }
}

async function processWebcamFrame() {
    if (!isCaptureLoopRunning || !activeStream || webcam.videoWidth === 0) return;

    // Capture current frame to an invisible canvas
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = webcam.videoWidth;
    tempCanvas.height = webcam.videoHeight;
    const tempCtx = tempCanvas.getContext("2d");
    
    // Draw current frame
    tempCtx.drawImage(webcam, 0, 0, tempCanvas.width, tempCanvas.height);
    const base64Image = tempCanvas.toDataURL("image/jpeg", 0.7); // compression to speed up REST payload

    try {
        const response = await fetch(`${API_URL}/api/sessions/process-frame`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: activeSessionId,
                image_base64: base64Image
            })
        });

        const data = await response.json();
        if (data.success) {
            drawFaceBoundingBoxes(data.results);
            updateLiveDetectionRoster(data.results);
        }
    } catch (e) {
        console.error("Frame recognition error:", e);
    }
}

function drawFaceBoundingBoxes(results) {
    // Canvas dimensions setup to map video frame coordinate scaling
    const rect = webcam.getBoundingClientRect();
    canvasOverlay.width = rect.width;
    canvasOverlay.height = rect.height;
    
    // Clear previous drawing
    ctxOverlay.clearRect(0, 0, canvasOverlay.width, canvasOverlay.height);

    const scaleX = canvasOverlay.width / webcam.videoWidth;
    const scaleY = canvasOverlay.height / webcam.videoHeight;

    results.forEach(face => {
        const box = face.box;
        // Bounding box dimensions
        const x = box.left * scaleX;
        const y = box.top * scaleY;
        const w = (box.right - box.left) * scaleX;
        const h = (box.bottom - box.top) * scaleY;

        // Pick color: Neon Blue/Green for recognized students, orange/red for unknown faces
        const color = face.status === "success" ? "#10b981" : "#f59e0b";
        
        ctxOverlay.strokeStyle = color;
        ctxOverlay.lineWidth = 3;
        ctxOverlay.shadowBlur = 8;
        ctxOverlay.shadowColor = color;
        ctxOverlay.strokeRect(x, y, w, h);

        // Draw Name / Confidence Card above bounding box
        ctxOverlay.shadowBlur = 0;
        ctxOverlay.fillStyle = color;
        ctxOverlay.font = "bold 13px Outfit";
        
        const label = `${face.name} (${face.confidence}%)`;
        const textWidth = ctxOverlay.measureText(label).width;
        
        ctxOverlay.fillRect(x - 1, y - 25, textWidth + 16, 25);
        
        ctxOverlay.fillStyle = "#ffffff";
        ctxOverlay.fillText(label, x + 8, y - 8);
    });
}

function updateLiveDetectionRoster(results) {
    let newDetections = false;
    
    results.forEach(face => {
        if (face.status === "success" && face.prn) {
            const prn = face.prn;
            
            if (!presentStudents.has(prn)) {
                presentStudents.add(prn);
                newDetections = true;
            }

            // Update details
            studentDetails[prn] = {
                name: face.name,
                prn: prn,
                last_seen: new Date().toLocaleTimeString()
            };
        }
    });

    if (newDetections || results.length > 0) {
        updateLiveRosterUI();
    }
}

async function updateLiveRosterUI() {
    statPresentCount.textContent = presentStudents.size;
    rosterCountBadge.textContent = `${presentStudents.size} Present`;

    if (presentStudents.size === 0) {
        liveRosterBody.innerHTML = `
            <tr class="empty-row">
                <td colspan="4">No students detected yet in this session.</td>
            </tr>
        `;
        return;
    }

    // Retrieve active student list from DB to get roll numbers
    let dbStudents = [];
    try {
        const res = await fetch(`${API_URL}/api/students`);
        dbStudents = await res.json();
    } catch(e) {
        console.error(e);
    }

    liveRosterBody.innerHTML = "";
    
    // Sort present students by roll number
    const list = Array.from(presentStudents).map(prn => {
        const details = studentDetails[prn];
        const match = dbStudents.find(s => s.prn === prn);
        return {
            roll_no: match ? match.roll_no : "--",
            name: details.name,
            prn: prn,
            last_seen: details.last_seen
        };
    }).sort((a, b) => a.roll_no - b.roll_no);

    list.forEach(student => {
        const row = `
            <tr>
                <td><strong>${student.roll_no}</strong></td>
                <td>${student.name}</td>
                <td>${student.prn}</td>
                <td><span class="status-pill present">${student.last_seen}</span></td>
            </tr>
        `;
        liveRosterBody.insertAdjacentHTML("beforeend", row);
    });
}

// ------------------ ENROLLMENT LOGIC ------------------
async function startEnrollWebcam() {
    try {
        enrollStream = await navigator.mediaDevices.getUserMedia({ video: true });
        enrollVideo.srcObject = enrollStream;
    } catch (e) {
        console.error("Enrollment camera failure", e);
    }
}

function stopEnrollWebcam() {
    if (enrollStream) {
        enrollStream.getTracks().forEach(track => track.stop());
        enrollStream = null;
    }
    enrollVideo.srcObject = null;
}

function captureEnrollPhoto() {
    // Draw frame to internal canvas
    enrollCanvas.width = enrollVideo.videoWidth;
    enrollCanvas.height = enrollVideo.videoHeight;
    const ctx = enrollCanvas.getContext("2d");
    ctx.drawImage(enrollVideo, 0, 0, enrollCanvas.width, enrollCanvas.height);
    
    const base64Data = enrollCanvas.toDataURL("image/jpeg");
    capturedImg.src = base64Data;
    
    // Toggle displays
    enrollVideo.classList.add("hide");
    capturedImg.classList.remove("hide");
    btnCapture.classList.add("hide");
    btnRetake.classList.remove("hide");

    // Face validation checks
    validateCapturedFace(base64Data);
}

function retakeEnrollPhoto() {
    capturedImg.src = "";
    enrollVideo.classList.remove("hide");
    capturedImg.classList.add("hide");
    btnCapture.classList.remove("hide");
    btnRetake.classList.add("hide");
    
    qualityAlert.className = "alert-box hide";
    btnSubmitEnroll.disabled = false;
}

async function validateCapturedFace(base64Data) {
    qualityAlert.className = "alert-box";
    qualityAlert.classList.remove("hide");
    qualityMsg.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Checking photo face validation...`;
    
    // Send a dry-run detection request
    try {
        const response = await fetch(`${API_URL}/api/sessions/process-frame`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: 0, image_base64: base64Data })
        });
        
        const data = await response.json();
        
        if (data.results.length === 0) {
            qualityAlert.className = "alert-box error";
            qualityMsg.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Face validation error: No face detected. Adjust lighting and retake.`;
            btnSubmitEnroll.disabled = true;
        } else if (data.results.length > 1) {
            qualityAlert.className = "alert-box error";
            qualityMsg.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Multi-face detected. Ensure only one person is in view.`;
            btnSubmitEnroll.disabled = true;
        } else {
            qualityAlert.className = "alert-box success";
            qualityMsg.innerHTML = `<i class="fa-solid fa-circle-check"></i> High face quality verified (Confidence: ${data.results[0].confidence}%). Ready to enroll.`;
            btnSubmitEnroll.disabled = false;
        }
    } catch(e) {
        qualityAlert.className = "alert-box error";
        qualityMsg.textContent = "Quality verification system offline.";
    }
}

async function submitEnrollment(e) {
    e.preventDefault();
    
    const prn = document.getElementById("enroll-prn").value;
    const classId = enrollClassSelect.value;
    const name = document.getElementById("enroll-name").value;
    const rollNo = document.getElementById("enroll-roll").value;
    const email = document.getElementById("enroll-email").value;
    const imageBase64 = capturedImg.src;

    if (!imageBase64) {
        alert("Please capture a photo first.");
        return;
    }

    const formData = new FormData();
    formData.append("prn", prn);
    formData.append("class_id", parseInt(classId));
    formData.append("name", name);
    formData.append("roll_no", parseInt(rollNo));
    formData.append("email", email);
    formData.append("image_base64", imageBase64);

    try {
        btnSubmitEnroll.disabled = true;
        btnSubmitEnroll.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving Enrollment...`;
        
        const response = await fetch(`${API_URL}/api/students/enroll`, {
            method: "POST",
            body: formData
        });

        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || "Enrollment failed");
        }

        alert("Student Enrolled successfully!");
        
        // Reset form & view
        enrollForm.reset();
        retakeEnrollPhoto();
        
        // Reset submit button state
        btnSubmitEnroll.disabled = false;
        btnSubmitEnroll.innerHTML = `<i class="fa-solid fa-user-plus"></i> Complete Enrollment`;
    } catch(error) {
        alert("Enrollment failed: " + error.message);
        btnSubmitEnroll.disabled = false;
        btnSubmitEnroll.innerHTML = `<i class="fa-solid fa-user-plus"></i> Complete Enrollment`;
    }
}

// ------------------ RESULTS & MODAL DISPLAY ------------------
let lastSessionResults = []; // Saved for CSV exports
let lastSessionSubject = "";

function showSessionResults(results) {
    lastSessionResults = results;
    
    // Find subject name
    const subjectName = subjectSelect.options[subjectSelect.selectedIndex].text;
    lastSessionSubject = subjectName;

    resultsTbody.innerHTML = "";
    
    resTotalReg.textContent = results.length;
    // Filter to only present students for present counts
    const presentCount = results.filter(r => r.status === "present").length;
    resTotalPresent.textContent = presentCount;

    // Display all students who were registered, sorting by Roll No
    results.sort((a, b) => a.roll_no - b.roll_no).forEach(student => {
        const isPresent = student.status === "present";
        const pillClass = isPresent ? "present" : "absent";
        const row = `
            <tr>
                <td><strong>${student.roll_no}</strong></td>
                <td>${student.name}</td>
                <td>${student.prn}</td>
                <td>${student.presence_percentage}%</td>
                <td><span class="status-pill ${pillClass}">${student.status}</span></td>
            </tr>
        `;
        resultsTbody.insertAdjacentHTML("beforeend", row);
    });

    resultsModal.classList.add("active");

    // CSV Download trigger mapping
    btnDownloadCsv.onclick = downloadAttendanceCSV;
}

function downloadAttendanceCSV() {
    // Generate only the Present students list
    const presentList = lastSessionResults.filter(r => r.status === "present");
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Roll No,Name,PRN,Presence Percentage,Status\n";

    presentList.forEach(r => {
        csvContent += `${r.roll_no},"${r.name}",${r.prn},${r.presence_percentage}%,Present\n`;
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);

    // Dynamic clean formatting: present_students_subject_date.csv
    const subjectClean = lastSessionSubject.replace(/ /g, "_").replace(/[^\w-]/g, "");
    const dateClean = new Date().toISOString().split('T')[0];
    
    link.setAttribute("download", `present_students_${subjectClean}_${dateClean}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ------------------ ARCHIVE & REPORTS PANEL ------------------
let systemLogsCache = [];

async function fetchSystemLogs() {
    try {
        const response = await fetch(`${API_URL}/api/attendance`);
        systemLogsCache = await response.json();
        
        // Ensure students cache is loaded for mapping
        if (enrolledStudentsCache.length === 0) {
            const resStud = await fetch(`${API_URL}/api/students`);
            enrolledStudentsCache = await resStud.json();
        }
        
        renderLogsTree();
    } catch(e) {
        console.error(e);
        const logsTree = document.getElementById("logs-tree");
        if (logsTree) logsTree.innerHTML = `<p class="center text-danger">Failed to fetch logs.</p>`;
    }
}

function renderLogsTree() {
    const logsTree = document.getElementById("logs-tree");
    if (!logsTree) return;
    
    logsTree.innerHTML = "";
    
    if (classes.length === 0) {
        logsTree.innerHTML = `<p class="center">No classes available.</p>`;
        return;
    }
    
    classes.forEach(cls => {
        // Create class node
        const classNode = document.createElement("div");
        classNode.className = "tree-class-node";
        
        const classHeader = document.createElement("div");
        classHeader.className = "tree-class-header";
        classHeader.innerHTML = `
            <span><i class="fa-solid fa-graduation-cap"></i> ${cls.name}</span>
            <i class="fa-solid fa-chevron-right"></i>
        `;
        
        const classContent = document.createElement("div");
        classContent.className = "tree-class-content";
        
        // Find semesters of subjects
        const semesters = [...new Set(subjects.map(s => s.semester))].sort((a, b) => a - b);
        
        semesters.forEach(sem => {
            const semNode = document.createElement("div");
            semNode.className = "tree-sem-node";
            
            const semHeader = document.createElement("div");
            semHeader.className = "tree-sem-header";
            semHeader.innerHTML = `
                <span><i class="fa-solid fa-book-bookmark"></i> Semester ${sem}</span>
                <i class="fa-solid fa-chevron-right"></i>
            `;
            
            const semContent = document.createElement("div");
            semContent.className = "tree-sem-content";
            
            // Subjects in this semester
            const semSubjects = subjects.filter(s => s.semester === sem);
            
            semSubjects.forEach(sub => {
                const subItem = document.createElement("div");
                subItem.className = "tree-subject-item";
                subItem.title = `${sub.name} (${sub.code || ''})`;
                subItem.textContent = `${sub.name}`;
                subItem.addEventListener("click", (e) => {
                    e.stopPropagation();
                    // Remove active from other items
                    document.querySelectorAll(".tree-subject-item").forEach(item => item.classList.remove("active"));
                    subItem.classList.add("active");
                    // Load report for this class and subject
                    showLogsReport(cls.id, cls.name, sub.id, sub.name);
                });
                semContent.appendChild(subItem);
            });
            
            semHeader.addEventListener("click", (e) => {
                e.stopPropagation();
                semNode.classList.toggle("open");
            });
            
            semNode.appendChild(semHeader);
            semNode.appendChild(semContent);
            classContent.appendChild(semNode);
        });
        
        classHeader.addEventListener("click", () => {
            classNode.classList.toggle("open");
        });
        
        classNode.appendChild(classHeader);
        classNode.appendChild(classContent);
        logsTree.appendChild(classNode);
    });
}

function showLogsReport(classId, className, subjectId, subjectName) {
    const placeholder = document.getElementById("logs-placeholder");
    const reportView = document.getElementById("logs-report-view");
    const titleSub = document.getElementById("report-title-subject");
    const titleCls = document.getElementById("report-title-class");
    
    if (placeholder) placeholder.classList.add("hide");
    if (reportView) reportView.classList.remove("hide");
    
    if (titleSub) titleSub.textContent = subjectName;
    if (titleCls) titleCls.textContent = className;
    
    // Filter class students
    const classStudents = enrolledStudentsCache.filter(s => s.class_id === classId);
    
    // Filter logs for this subject and these students
    const subjectLogs = systemLogsCache.filter(log => log.subject_id === subjectId && classStudents.some(s => s.prn === log.prn));
    
    // Find unique session IDs
    const sessionIds = [...new Set(subjectLogs.map(log => log.session_id))].sort((a, b) => b - a);
    
    const sessionSelect = document.getElementById("report-session-select");
    if (sessionSelect) {
        sessionSelect.innerHTML = `<option value="cumulative">Cumulative Summary</option>`;
        sessionIds.forEach(sid => {
            const sampleLog = subjectLogs.find(log => log.session_id === sid);
            const dateStr = sampleLog ? new Date(sampleLog.timestamp).toLocaleDateString() + " " + new Date(sampleLog.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '';
            const opt = `<option value="${sid}">Session #${sid} (${dateStr})</option>`;
            sessionSelect.insertAdjacentHTML("beforeend", opt);
        });
    }
    
    // Reset search
    if (reportSearch) reportSearch.value = "";
    
    window.currentReportContext = { classId, className, subjectId, subjectName, classStudents, subjectLogs, sessionIds };
    
    renderLogsReportTable();
}

function renderLogsReportTable() {
    if (!window.currentReportContext) return;
    const { classStudents, subjectLogs, sessionIds } = window.currentReportContext;
    
    const sessionSelect = document.getElementById("report-session-select");
    const selectedMode = sessionSelect ? sessionSelect.value : "cumulative";
    
    const thead = document.getElementById("report-table-thead");
    const tbody = document.getElementById("report-table-tbody");
    
    if (!thead || !tbody) return;
    
    const searchQuery = reportSearch ? reportSearch.value.toLowerCase().trim() : "";
    
    // Filter students by search query if any
    const filteredStudents = classStudents.filter(s => {
        if (!searchQuery) return true;
        return s.name.toLowerCase().includes(searchQuery) || s.prn.toLowerCase().includes(searchQuery) || s.roll_no.toString().includes(searchQuery);
    });
    
    tbody.innerHTML = "";
    
    if (selectedMode === "cumulative") {
        thead.innerHTML = `
            <tr>
                <th>Roll No</th>
                <th>PRN</th>
                <th>Student Name</th>
                <th class="center">Total Sessions</th>
                <th class="center">Sessions Attended</th>
                <th class="center">Average Presence %</th>
                <th>Overall Status</th>
            </tr>
        `;
        
        if (filteredStudents.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="center">No matching student records found.</td></tr>`;
            return;
        }
        
        filteredStudents.forEach(student => {
            const studLogs = subjectLogs.filter(log => log.prn === student.prn);
            const totalSessions = sessionIds.length;
            const sessionsAttended = studLogs.filter(log => log.status === "present").length;
            const avgPresence = totalSessions > 0 ? (studLogs.reduce((sum, log) => sum + log.presence_percentage, 0) / totalSessions) : 0.0;
            const status = avgPresence >= 70.0 ? "present" : "absent";
            const pillClass = status === "present" ? "present" : "absent";
            
            const row = `
                <tr>
                    <td><strong>${student.roll_no}</strong></td>
                    <td><code>${student.prn}</code></td>
                    <td>${student.name}</td>
                    <td class="center">${totalSessions}</td>
                    <td class="center">${sessionsAttended}</td>
                    <td class="center">${avgPresence.toFixed(1)}%</td>
                    <td><span class="status-pill ${pillClass}">${status}</span></td>
                </tr>
            `;
            tbody.insertAdjacentHTML("beforeend", row);
        });
    } else {
        const sessionId = parseInt(selectedMode);
        thead.innerHTML = `
            <tr>
                <th>Roll No</th>
                <th>PRN</th>
                <th>Student Name</th>
                <th class="center">Presence %</th>
                <th>Session Status</th>
            </tr>
        `;
        
        if (filteredStudents.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="center">No matching student records found.</td></tr>`;
            return;
        }
        
        filteredStudents.forEach(student => {
            const log = subjectLogs.find(l => l.prn === student.prn && l.session_id === sessionId);
            const presence = log ? log.presence_percentage : 0.0;
            const status = log ? log.status : "absent";
            const pillClass = status === "present" ? "present" : "absent";
            
            const row = `
                <tr>
                    <td><strong>${student.roll_no}</strong></td>
                    <td><code>${student.prn}</code></td>
                    <td>${student.name}</td>
                    <td class="center">${presence.toFixed(1)}%</td>
                    <td><span class="status-pill ${pillClass}">${status}</span></td>
                </tr>
            `;
            tbody.insertAdjacentHTML("beforeend", row);
        });
    }
}

function filterLogs() {
    if (window.currentReportContext) {
        renderLogsReportTable();
    }
}

function exportReportToCSV() {
    if (!window.currentReportContext) return;
    const { className, subjectName, classStudents, subjectLogs, sessionIds } = window.currentReportContext;
    
    const sessionSelect = document.getElementById("report-session-select");
    const selectedMode = sessionSelect ? sessionSelect.value : "cumulative";
    
    let csvContent = "data:text/csv;charset=utf-8,";
    let filename = "";
    
    const subjectClean = subjectName.replace(/ /g, "_").replace(/[^\w-]/g, "");
    const classClean = className.replace(/ /g, "_").replace(/[^\w-]/g, "");
    const dateClean = new Date().toISOString().split('T')[0];
    
    if (selectedMode === "cumulative") {
        csvContent += "Roll No,PRN,Student Name,Total Sessions,Sessions Attended,Average Presence %,Status\n";
        classStudents.forEach(student => {
            const studLogs = subjectLogs.filter(log => log.prn === student.prn);
            const totalSessions = sessionIds.length;
            const sessionsAttended = studLogs.filter(log => log.status === "present").length;
            const avgPresence = totalSessions > 0 ? (studLogs.reduce((sum, log) => sum + log.presence_percentage, 0) / totalSessions) : 0.0;
            const status = avgPresence >= 70.0 ? "present" : "absent";
            csvContent += `${student.roll_no},${student.prn},"${student.name}",${totalSessions},${sessionsAttended},${avgPresence.toFixed(1)}%,${status}\n`;
        });
        filename = `cumulative_attendance_${subjectClean}_${classClean}_${dateClean}.csv`;
    } else {
        const sessionId = parseInt(selectedMode);
        csvContent += "Roll No,PRN,Student Name,Presence %,Status\n";
        classStudents.forEach(student => {
            const log = subjectLogs.find(l => l.prn === student.prn && l.session_id === sessionId);
            const presence = log ? log.presence_percentage : 0.0;
            const status = log ? log.status : "absent";
            csvContent += `${student.roll_no},${student.prn},"${student.name}",${presence.toFixed(1)}%,${status}\n`;
        });
        filename = `session_${sessionId}_attendance_${subjectClean}_${classClean}_${dateClean}.csv`;
    }
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ------------------ DYNAMIC SUBJECT DROPDOWNS ------------------
function populateSubjectsFiltered() {
    const selectedSem = semesterSelect.value;
    subjectSelect.innerHTML = `<option value="">Select Subject...</option>`;
    
    if (!selectedSem) {
        subjectSelect.innerHTML = `<option value="">Select Semester First...</option>`;
        return;
    }
    
    const filtered = subjects.filter(s => s.semester === parseInt(selectedSem));
    if (filtered.length === 0) {
        subjectSelect.innerHTML = `<option value="">No subjects in this semester</option>`;
        return;
    }
    
    filtered.forEach(s => {
        const opt = `<option value="${s.id}">${s.name} (${s.code || ''})</option>`;
        subjectSelect.insertAdjacentHTML("beforeend", opt);
    });
}

// ------------------ MANAGE STUDENTS DIRECTORY ------------------
let enrolledStudentsCache = [];

async function loadEnrolledStudents() {
    if (!studentListBody) return;
    studentListBody.innerHTML = `<tr><td colspan="6" class="center"><i class="fa-solid fa-spinner fa-spin"></i> Loading students list...</td></tr>`;
    
    try {
        const response = await fetch(`${API_URL}/api/students`);
        enrolledStudentsCache = await response.json();
        renderEnrolledStudents(enrolledStudentsCache);
    } catch(e) {
        console.error(e);
        studentListBody.innerHTML = `<tr><td colspan="6" class="center text-danger">Failed to fetch student records.</td></tr>`;
    }
}

function renderEnrolledStudents(studentList) {
    if (studentList.length === 0) {
        studentListBody.innerHTML = `<tr><td colspan="6" class="center">No enrolled students in database.</td></tr>`;
        return;
    }
    
    studentListBody.innerHTML = "";
    studentList.forEach(student => {
        const classObj = classes.find(c => c.id === student.class_id);
        const className = classObj ? classObj.name : `Class ID: ${student.class_id}`;
        
        const row = `
            <tr>
                <td><strong>${student.roll_no}</strong></td>
                <td>${student.name}</td>
                <td><code>${student.prn}</code></td>
                <td>${className}</td>
                <td>${student.email || '--'}</td>
                <td>
                    <div class="action-btn-group">
                        <button onclick="openEditStudentModal('${student.prn}')" class="btn-edit-tbl">
                            <i class="fa-solid fa-pen-to-square"></i> Edit
                        </button>
                        <button onclick="confirmDeleteStudent('${student.prn}')" class="btn-delete-tbl">
                            <i class="fa-solid fa-trash-can"></i> Delete
                        </button>
                    </div>
                </td>
            </tr>
        `;
        studentListBody.insertAdjacentHTML("beforeend", row);
    });
}

function filterStudents() {
    const q = studentSearch.value.toLowerCase();
    const filtered = enrolledStudentsCache.filter(student => {
        return student.name.toLowerCase().includes(q) || 
               student.prn.toLowerCase().includes(q) || 
               student.roll_no.toString().includes(q);
    });
    renderEnrolledStudents(filtered);
}

// Global hook window methods to allow table button onclick actions
window.openEditStudentModal = async function(prn) {
    const student = enrolledStudentsCache.find(s => s.prn === prn);
    if (!student) return;
    
    // Prefill fields
    editPrnInput.value = student.prn;
    editClassSelect.value = student.class_id;
    editNameInput.value = student.name;
    editRollInput.value = student.roll_no;
    editEmailInput.value = student.email || "";
    
    // Reset photo section
    editCapturedImageBase64 = null;
    editCapturedImg.src = "";
    editCapturedImg.classList.add("hide");
    editVideo.classList.add("hide");
    if (btnEditCapture) btnEditCapture.classList.add("hide");
    if (btnEditRetake) btnEditRetake.classList.add("hide");
    if (editPhotoPlaceholder) editPhotoPlaceholder.classList.remove("hide");
    if (editQualityAlert) editQualityAlert.className = "alert-box hide";
    btnSubmitEdit.disabled = false;
    btnSubmitEdit.innerHTML = `<i class="fa-solid fa-save"></i> Save Profile Changes`;
    
    // Open Modal
    editStudentModal.classList.remove("hide");
    editStudentModal.classList.add("active");
};

window.confirmDeleteStudent = async function(prn) {
    if (!confirm(`Are you sure you want to permanently delete student with PRN: ${prn}?\nThis action will also delete all associated face encodings and cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/api/students/${prn}`, {
            method: "DELETE"
        });
        
        const data = await response.json();
        if (response.ok) {
            alert("Student deleted successfully!");
            loadEnrolledStudents();
        } else {
            throw new Error(data.detail || "Delete operation failed");
        }
    } catch(e) {
        alert("Error: " + e.message);
    }
};

// ------------------ EDIT WEBCAM CONTROLS ------------------
async function startEditWebcam() {
    try {
        editStream = await navigator.mediaDevices.getUserMedia({ video: true });
        editVideo.srcObject = editStream;
        
        editVideo.classList.remove("hide");
        editPhotoPlaceholder.classList.add("hide");
        editCapturedImg.classList.add("hide");
        
        btnEditActivateCam.classList.add("hide");
        btnEditCapture.classList.remove("hide");
        btnEditRetake.classList.add("hide");
    } catch(e) {
        console.error("Edit webcam failure", e);
        alert("Failed to access camera.");
    }
}

function stopEditWebcam() {
    if (editStream) {
        editStream.getTracks().forEach(track => track.stop());
        editStream = null;
    }
    editVideo.srcObject = null;
    editVideo.classList.add("hide");
    btnEditActivateCam.classList.remove("hide");
    if (btnEditCapture) btnEditCapture.classList.add("hide");
    if (btnEditRetake) btnEditRetake.classList.add("hide");
}

function captureEditPhoto() {
    editCanvas.width = editVideo.videoWidth;
    editCanvas.height = editVideo.videoHeight;
    const ctx = editCanvas.getContext("2d");
    ctx.drawImage(editVideo, 0, 0, editCanvas.width, editCanvas.height);
    
    editCapturedImageBase64 = editCanvas.toDataURL("image/jpeg");
    editCapturedImg.src = editCapturedImageBase64;
    
    editVideo.classList.add("hide");
    editCapturedImg.classList.remove("hide");
    btnEditCapture.classList.add("hide");
    btnEditRetake.classList.remove("hide");
    
    validateEditFace(editCapturedImageBase64);
}

function retakeEditPhoto() {
    editCapturedImageBase64 = null;
    editCapturedImg.src = "";
    editVideo.classList.remove("hide");
    editCapturedImg.classList.add("hide");
    btnEditCapture.classList.remove("hide");
    btnEditRetake.classList.add("hide");
    
    editQualityAlert.className = "alert-box hide";
    btnSubmitEdit.disabled = false;
}

async function validateEditFace(base64Data) {
    editQualityAlert.className = "alert-box";
    editQualityAlert.classList.remove("hide");
    editQualityMsg.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Checking photo face validation...`;
    
    try {
        const response = await fetch(`${API_URL}/api/sessions/process-frame`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: 0, image_base64: base64Data })
        });
        
        const data = await response.json();
        
        if (data.results.length === 0) {
            editQualityAlert.className = "alert-box error";
            editQualityMsg.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Face validation error: No face detected. Adjust lighting and retake.`;
            btnSubmitEdit.disabled = true;
        } else if (data.results.length > 1) {
            editQualityAlert.className = "alert-box error";
            editQualityMsg.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Multi-face detected. Ensure only one person is in view.`;
            btnSubmitEdit.disabled = true;
        } else {
            editQualityAlert.className = "alert-box success";
            editQualityMsg.innerHTML = `<i class="fa-solid fa-circle-check"></i> High face quality verified (Confidence: ${data.results[0].confidence}%). Ready.`;
            btnSubmitEdit.disabled = false;
        }
    } catch(e) {
        editQualityAlert.className = "alert-box error";
        editQualityMsg.textContent = "Quality verification system offline.";
    }
}

async function submitEditStudent(e) {
    e.preventDefault();
    
    const prn = editPrnInput.value;
    const classId = editClassSelect.value;
    const name = editNameInput.value;
    const rollNo = editRollInput.value;
    const email = editEmailInput.value;
    
    const formData = new FormData();
    formData.append("class_id", parseInt(classId));
    formData.append("name", name);
    formData.append("roll_no", parseInt(rollNo));
    formData.append("email", email);
    if (editCapturedImageBase64) {
        formData.append("image_base64", editCapturedImageBase64);
    }
    
    try {
        btnSubmitEdit.disabled = true;
        btnSubmitEdit.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving changes...`;
        
        const response = await fetch(`${API_URL}/api/students/${prn}/edit`, {
            method: "POST",
            body: formData
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || "Edit operation failed");
        }
        
        alert("Student details updated successfully!");
        editStudentModal.classList.remove("active");
        editStudentModal.classList.add("hide");
        stopEditWebcam();
        loadEnrolledStudents();
    } catch(error) {
        alert("Failed to update student: " + error.message);
        btnSubmitEdit.disabled = false;
        btnSubmitEdit.innerHTML = `<i class="fa-solid fa-save"></i> Save Profile Changes`;
    }
}

// ------------------ ATTENDANCE ANALYTICS LOGIC ------------------
let subjectsBarChart = null;
let sessionsLineChart = null;

async function initAnalyticsTab() {
    populateAnalyticsDropdowns();
    fetchAndDrawCharts();
}

function populateAnalyticsDropdowns() {
    const classSelectAn = document.getElementById("analytics-class-select");
    const subjSelectAn = document.getElementById("analytics-subject-select");
    
    if (!classSelectAn || !subjSelectAn) return;
    
    if (classSelectAn.options.length <= 1) {
        classSelectAn.innerHTML = `<option value="">Select Class...</option>`;
        classes.forEach(c => {
            classSelectAn.insertAdjacentHTML("beforeend", `<option value="${c.id}">${c.name}</option>`);
        });
        classSelectAn.addEventListener("change", fetchAndDrawCharts);
    }
    
    if (subjSelectAn.options.length <= 1) {
        subjSelectAn.innerHTML = `<option value="">Select Subject...</option>`;
        subjects.forEach(s => {
            subjSelectAn.insertAdjacentHTML("beforeend", `<option value="${s.id}">${s.name} (${s.code || ''})</option>`);
        });
        subjSelectAn.addEventListener("change", fetchAndDrawCharts);
    }
    
    if (!classSelectAn.value && classes.length > 0) {
        classSelectAn.value = classes[0].id;
    }
    if (!subjSelectAn.value && subjects.length > 0) {
        subjSelectAn.value = subjects[0].id;
    }
}

async function fetchAndDrawCharts() {
    const classId = document.getElementById("analytics-class-select").value;
    const subjectId = document.getElementById("analytics-subject-select").value;
    
    if (!classId || !subjectId) return;
    
    try {
        const response = await fetch(`${API_URL}/api/analytics/class-subject-stats?class_id=${classId}&subject_id=${subjectId}`);
        if (!response.ok) throw new Error("Failed to fetch analytics");
        
        const data = await response.json();
        drawSubjectsBarChart(data.subject_averages);
        drawSessionsLineChart(data.session_trends);
    } catch(e) {
        console.error("Analytics chart render failure:", e);
    }
}

function drawSubjectsBarChart(subjectAverages) {
    const ctx = document.getElementById("subjects-bar-chart").getContext("2d");
    if (!ctx) return;
    
    if (subjectsBarChart) {
        subjectsBarChart.destroy();
    }
    
    const labels = subjectAverages.map(s => s.subject_name.length > 20 ? s.subject_name.substring(0, 17) + "..." : s.subject_name);
    const datasetData = subjectAverages.map(s => s.avg_attendance);
    
    const backgroundColors = datasetData.map(val => val >= 70.0 ? "rgba(16, 185, 129, 0.6)" : "rgba(239, 68, 68, 0.6)");
    const borderColors = datasetData.map(val => val >= 70.0 ? "rgba(16, 185, 129, 1)" : "rgba(239, 68, 68, 1)");

    subjectsBarChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Class Average Attendance %',
                data: datasetData,
                backgroundColor: backgroundColors,
                borderColor: borderColors,
                borderWidth: 2,
                borderRadius: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function drawSessionsLineChart(sessionTrends) {
    const ctx = document.getElementById("sessions-line-chart").getContext("2d");
    if (!ctx) return;
    
    if (sessionsLineChart) {
        sessionsLineChart.destroy();
    }
    
    const labels = sessionTrends.map(s => {
        const d = new Date(s.start_time);
        return d.toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) + " #" + s.session_id;
    });
    const datasetData = sessionTrends.map(s => s.avg_attendance);

    sessionsLineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Presence Average %',
                data: datasetData,
                borderColor: '#2196F3',
                backgroundColor: 'rgba(33, 150, 243, 0.1)',
                borderWidth: 3,
                fill: true,
                tension: 0.3,
                pointBackgroundColor: '#2196F3',
                pointRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

// ------------------ AI CHAT INTERFACE LIFE-CYCLE ------------------
let isChatInitialized = false;

function initChatTab() {
    if (isChatInitialized) return;
    isChatInitialized = true;
    
    const chatForm = document.getElementById("chat-input-form");
    const chatInput = document.getElementById("chat-user-input");
    const chatTimeline = document.getElementById("chat-messages-timeline");
    
    if (chatForm) {
        chatForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const messageText = chatInput.value.trim();
            if (!messageText) return;
            
            chatInput.value = "";
            
            // 1. Append User Message
            appendChatMessage("user", messageText);
            
            // 2. Append Assistant Loading Bubble
            const loadingBubbleId = appendChatLoadingBubble();
            
            // Scroll to bottom
            chatTimeline.scrollTop = chatTimeline.scrollHeight;
            
            try {
                const response = await fetch(`${API_URL}/api/chat`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ message: messageText })
                });
                
                const data = await response.json();
                removeChatLoadingBubble(loadingBubbleId);
                
                if (response.ok && data.success) {
                    appendChatMessage("assistant", data.response, data.sql, data.results);
                } else {
                    appendChatMessage("assistant", `Sorry, I encountered an error: ${data.response || "Unknown error"}`);
                }
            } catch (err) {
                removeChatLoadingBubble(loadingBubbleId);
                appendChatMessage("assistant", `Unable to reach the assistant service. Error details: ${err.message}`);
            }
            
            chatTimeline.scrollTop = chatTimeline.scrollHeight;
        });
    }
    
    // Bind quick suggestions click
    const suggestionBtns = document.querySelectorAll(".suggestion-btn");
    suggestionBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const query = btn.getAttribute("data-query");
            if (chatInput) {
                chatInput.value = query;
                chatInput.focus();
            }
        });
    });
}

function appendChatMessage(sender, text, sql = "", results = null) {
    const chatTimeline = document.getElementById("chat-messages-timeline");
    if (!chatTimeline) return;
    
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${sender}`;
    
    const bubbleDiv = document.createElement("div");
    bubbleDiv.className = "message-bubble";
    
    // Simple markdown-style conversions for formatting
    let formattedText = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
        
    bubbleDiv.innerHTML = `<p>${formattedText}</p>`;
    
    // Render tabular results in bubble if returned
    if (Array.isArray(results) && results.length > 0) {
        const table = document.createElement("table");
        const keys = Object.keys(results[0]);
        
        // Build table head
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        keys.forEach(k => {
            const displayKey = k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
            trHead.insertAdjacentHTML("beforeend", `<th>${displayKey}</th>`);
        });
        thead.appendChild(trHead);
        table.appendChild(thead);
        
        // Build table body
        const tbody = document.createElement("tbody");
        results.forEach(row => {
            const trRow = document.createElement("tr");
            keys.forEach(k => {
                const val = row[k] !== null && row[k] !== undefined ? row[k] : "--";
                trRow.insertAdjacentHTML("beforeend", `<td>${val}</td>`);
            });
            tbody.appendChild(trRow);
        });
        table.appendChild(tbody);
        bubbleDiv.appendChild(table);
    }
    
    // Render toggle SQL query
    if (sql && sql !== "(None)" && sql.trim() !== "") {
        const sqlToggle = document.createElement("div");
        sqlToggle.className = "chat-sql-toggle";
        sqlToggle.innerHTML = `
            <div class="chat-sql-header" onclick="toggleChatSql(this)">
                <span><i class="fa-solid fa-database"></i> Executed PostgreSQL Query</span>
                <i class="fa-solid fa-chevron-down"></i>
            </div>
            <div class="chat-sql-body">${sql}</div>
        `;
        bubbleDiv.appendChild(sqlToggle);
    }
    
    messageDiv.appendChild(bubbleDiv);
    messageDiv.insertAdjacentHTML("beforeend", `<span class="message-time">${timeStr}</span>`);
    
    chatTimeline.appendChild(messageDiv);
    chatTimeline.scrollTop = chatTimeline.scrollHeight;
}

function appendChatLoadingBubble() {
    const chatTimeline = document.getElementById("chat-messages-timeline");
    if (!chatTimeline) return null;
    
    const bubbleId = "loading-" + Date.now();
    const loadingDiv = document.createElement("div");
    loadingDiv.className = "message assistant";
    loadingDiv.id = bubbleId;
    
    loadingDiv.innerHTML = `
        <div class="message-bubble">
            <div class="chat-bubble-loading">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;
    
    chatTimeline.appendChild(loadingDiv);
    chatTimeline.scrollTop = chatTimeline.scrollHeight;
    return bubbleId;
}

function removeChatLoadingBubble(bubbleId) {
    if (!bubbleId) return;
    const element = document.getElementById(bubbleId);
    if (element) {
        element.remove();
    }
}

window.toggleChatSql = function(headerElement) {
    headerElement.parentElement.classList.toggle("open");
}
