window.PDFViewerApplicationOptions = {
  set: function(name, value) {
    window.sessionStorage.setItem(`pdfjs.${name}`, value);
  },
  get: function(name, defaultValue) {
    return window.sessionStorage.getItem(`pdfjs.${name}`) || defaultValue;
  },
  remove: function(name) {
    window.sessionStorage.removeItem(`pdfjs.${name}`);
  }
};

window.PDFViewerApplicationOptions.set("annotationEditorMode", 0);
window.PDFViewerApplicationOptions.set("annotationMode", 0);
window.PDFViewerApplicationOptions.set("enableSignatureEditor", false);
window.PDFViewerApplicationOptions.set("enableHighlightFloatingButton", false);
window.PDFViewerApplicationOptions.set("enableUpdatedAddImage", false);
window.PDFViewerApplicationOptions.set("enableNewAltTextWhenAddingImage", false);
window.PDFViewerApplicationOptions.set("enablePermissions", false);

// Hide editor buttons
document.addEventListener("DOMContentLoaded", function() {
  const editorElements = document.querySelectorAll("#editorModeButtons, #editorModeSeparator");
  editorElements.forEach(function(element) {
    if (element) {
      element.classList.add("hidden");
    }
  });
});
