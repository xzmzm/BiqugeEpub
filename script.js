document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('epub-form');
    const urlInput = document.getElementById('url');
    const startInput = document.getElementById('start');
    const endInput = document.getElementById('end');
    const submitButton = document.getElementById('submit-btn');
    const logsArea = document.getElementById('logs');
    const downloadLinkArea = document.getElementById('download-link-area');

    // --- Helper Function to Log Messages ---
    function logMessage(message, isError = false) {
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.textContent = `[${timestamp}] ${message}`;
        if (isError) {
            logEntry.style.color = 'red';
            logEntry.style.fontWeight = 'bold';
        }
        logsArea.appendChild(logEntry);
        // Scroll to the bottom of the logs
        logsArea.scrollTop = logsArea.scrollHeight;
    }

    // --- Form Submission Handler ---
    form.addEventListener('submit', async (event) => {
        event.preventDefault(); // Prevent default form submission

        // --- Clear previous results and disable button ---
        logsArea.innerHTML = ''; // Clear previous logs
        downloadLinkArea.innerHTML = ''; // Clear previous download link
        submitButton.disabled = true;
        logMessage('Starting EPUB generation...');

        // --- Get form data ---
        const url = urlInput.value.trim();
        const startChapter = startInput.value.trim();
        const endChapter = endInput.value.trim();

        if (!url) {
            logMessage('Error: Book Index URL is required.', true);
            submitButton.disabled = false;
            return;
        }

        // --- Construct backend URL with query parameters ---
        // IMPORTANT: Replace '/generate-epub' with the actual path
        // where your fcgiwrap script is mapped by your web server (e.g., Nginx).
        const backendUrl = new URL('/generate-epub', window.location.origin);
        backendUrl.searchParams.append('url', url);
        if (startChapter) {
            backendUrl.searchParams.append('start', startChapter);
        }
        if (endChapter) {
            backendUrl.searchParams.append('end', endChapter);
        }

        logMessage(`Sending request to backend: ${backendUrl.pathname}${backendUrl.search}`);

        // --- Fetch EPUB from backend ---
        try {
            const response = await fetch(backendUrl.toString());

            logMessage(`Received response with status: ${response.status}`);

            if (response.ok && response.headers.get('Content-Type')?.includes('application/epub+zip')) {
                // --- Success: EPUB received ---
                logMessage('EPUB generation successful. Preparing download link...');

                // Extract filename from Content-Disposition header
                let filename = "generated_book.epub"; // Default filename
                const disposition = response.headers.get('Content-Disposition');
                if (disposition && disposition.includes('attachment')) {
                    // Try to extract filename* (RFC 5987)
                    const filenameStarRegex = /filename\*=UTF-8''([^;]+)/i;
                    const starMatches = filenameStarRegex.exec(disposition);
                    if (starMatches && starMatches[1]) {
                        try {
                            filename = decodeURIComponent(starMatches[1]);
                        } catch (e) {
                            logMessage(`Error decoding filename*: ${e}`, true);
                            // Fallback to simple filename if decoding fails
                            const filenameRegex = /filename="?([^";]+)"?/i;
                            const matches = filenameRegex.exec(disposition);
                            if (matches && matches[1]) {
                                filename = matches[1];
                            }
                        }
                    } else {
                        // Fallback to simple filename if filename* is not found
                        const filenameRegex = /filename="?([^";]+)"?/i;
                        const matches = filenameRegex.exec(disposition);
                        if (matches && matches[1]) {
                            filename = matches[1];
                        }
                    }
                }
                logMessage(`Filename: ${filename}`); // Should now log the correct filename

                // Get EPUB data as a Blob
                const epubBlob = await response.blob();
                logMessage(`EPUB size: ${(epubBlob.size / 1024).toFixed(2)} KB`);

                // Create a download link
                const downloadUrl = URL.createObjectURL(epubBlob);
                const downloadLink = document.createElement('a');
                downloadLink.href = downloadUrl;
                downloadLink.download = filename;
                downloadLink.textContent = `Download ${filename}`;
                downloadLinkArea.appendChild(downloadLink);

                logMessage('Download link created.');

            } else {
                // --- Error from backend ---
                const errorText = await response.text();
                logMessage(`Backend Error (Status ${response.status}): ${errorText || 'Unknown error'}`, true);
            }

        } catch (error) {
            // --- Network or other fetch error ---
            logMessage(`Network or fetch error: ${error.message}`, true);
            console.error("Fetch error details:", error);
        } finally {
            // --- Re-enable button ---
            submitButton.disabled = false;
            logMessage('Process finished.');
        }
    });
});