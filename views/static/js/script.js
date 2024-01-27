// Custom capitalize function
String.prototype.capitalize = function () {
    return this.charAt(0).toUpperCase() + this.slice(1);
};
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
}
