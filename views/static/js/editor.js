function showNotification(message, color) {
    const notification = document.createElement('div');
    notification.className = 'notification';
    notification.style.backgroundColor = color;
    notification.textContent = message;

    // Positioniere die Benachrichtigung
    notification.style.position = 'fixed';
    notification.style.top = document.body.children.length * 40 + 'px'; // 60px Abstand zwischen den Benachrichtigungen
    notification.style.right = '10px'; // Abstand vom rechten Rand
    notification.style.padding = '4px 12px';

    document.body.appendChild(notification);

    // Schließe die Benachrichtigung nach einigen Sekunden
    setTimeout(function () {
        document.body.removeChild(notification);
    }, 5000); // Schließe nach 5 Sekunden
}

function enableIpaddressInput(elem, id) {
    var input = document.getElementById(id);
    if (elem.checked) {
        // Input deaktivieren und Wert löschen
        input.disabled = true;
        input.value = '';
    } else {
        // Input aktivieren
        input.disabled = false;
    }
}

function clearGroup(elem) {
    var group = document.querySelectorAll("*[data_name]");
    var lastIndex = elem.name.lastIndexOf('_');
    var modifiedFieldName = elem.name.slice(0, lastIndex) + ':enabled';
    var element = document.querySelector('[name="' + modifiedFieldName + '"]');
    console.log('clearGroup modifiedFieldName: ' + modifiedFieldName)
    console.log('clearGroup group: ' + group)
    if (element && element.checked === false) {
        elem.checked = false;
        return;
    }
    for (var i = 0; i < group.length; i++) {
        if (group[i] != elem) {
            group[i].checked = false;
        } else {
            group[i].checked = true;
        }
    }
}

function addConfigEntry(paramName) {
    fetch('/add_config_entry', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            param_name: paramName,
        }),
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Hier kannst du die aktualisierte Konfiguration verwenden
                console.log('Updated Configuration:', data.config);
                config = data.config
                showNotification('Eintrag erfolgreich hinzugefügt', 'green');
            } else {
                // Hier kannst du Fehler behandeln
                console.error('Fehler beim Hinzufügen des Eintrags:', data.message);
                showNotification('Fehler beim Hinzufügen des Eintrags', 'red');
            }
        })
        .catch(error => {
            console.error('Fehler beim Kommunizieren mit dem Server:', error);
            showNotification('Es ist ein Fehler aufgetreten. Bitte versuche es erneut.', 'red');
        });
}

document.addEventListener('DOMContentLoaded', function () {
    var selectedSectionElement = document.getElementById('selectedSection');

    if (!selectedSectionElement) {
        console.error('Error: Element with ID "selectedSection" not found.');
        return;
    }

    // var allowedSections = ['pv_panels'];
    var allowedSections = [];

    // Fix: for not checked checkboxes
        var checkboxes = document.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(function (checkbox) {
            console.log(checkbox.id);
            var hiddenInput = document.getElementById(checkbox.id + '_hidden');
            hiddenInput.disabled = checkbox.checked;

            checkbox.addEventListener('change', function () {
                console.log(this.name);
                hiddenInput.disabled = this.checked;
            });
        });

    function updateSectionFields() {
        var selectedSection = selectedSectionElement.value;
        console.log('Selected section:', selectedSection);

        // Verstecke alle Abschnitte zuerst
        var allSections = document.querySelectorAll('[id^="sectionFields_"]');
        allSections.forEach(function (section) {
            section.style.display = 'none';
        });

        var sendSectionButton = document.getElementById('sendSectionButton');
        sendSectionButton.style.display = allowedSections.includes(selectedSection) && selectedSection !== '' ? 'inline-block' : 'none';

        // Zeige nur den ausgewählten Abschnitt
        if (selectedSection !== '') {
            var selectedSectionData = config[selectedSection];
            var selectedSectionDiv = document.getElementById('sectionFields_' + selectedSection);

            if (!selectedSectionDiv) {
                console.error('Error: Element with ID "sectionFields_' + selectedSection + '" not found.');
                return;
            }

            selectedSectionDiv.innerHTML = '';

            for (var i = 0; selectedSectionData && i < selectedSectionData.length; i++) {
                var currentItem = selectedSectionData[i];

                var fieldset = document.createElement('fieldset');
                var legend = document.createElement('legend');
                var currentItemName = names[currentItem.name.toLowerCase()];
                var currentItemName = names[currentItem.name.toLowerCase()] ?? currentItem.name;

                legend.appendChild(document.createTextNode(currentItemName));
                fieldset.appendChild(legend);

                for (var fieldKey in currentItem) {
                    if (fieldKey !== 'name') {
                        var label = document.createElement('label');
                        label.setAttribute('for', selectedSection + ':' + currentItem.name + ':' + fieldKey);
                        // fieldKey.capitalize()
                        const formattedText = fieldKey
                            .split("_")
                            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                            .join(" ");

                        if (tooltips && fieldKey in tooltips) {
                            label.appendChild(document.createTextNode(formattedText + " ℹ️"));
                            label.setAttribute('title', tooltips[fieldKey]);
                            label.setAttribute('class', "tooltip-icon");
                        } else {
                            label.appendChild(document.createTextNode(formattedText));
                        }

                        var input;
                        if (typeof currentItem[fieldKey] === 'boolean') {
                            input = document.createElement('input');
                            input.setAttribute('type', 'checkbox');
                            input.setAttribute('id', selectedSection + ':' + currentItem.name + ':' + fieldKey);
                            input.setAttribute('name', selectedSection + ':' + currentItem.name + ':' + fieldKey);
                            input.checked = currentItem[fieldKey]

                            if ('primary' === fieldKey) {
                                input.setAttribute('data_name', fieldKey);
                                input.addEventListener('input', function () {
                                    clearGroup(this);
                                });
                            }
                            if ('use_vrm' === fieldKey) {
                                input.setAttribute('data_name', fieldKey);
                                input.setAttribute('data_name_target', selectedSection + ':' + currentItem.name + ':ip_address');
                                input.addEventListener('input', function () {
                                    enableIpaddressInput(this, selectedSection + ':' + currentItem.name + ':ip_address');
                                });
                            }

                            var hiddenInput = document.createElement('input');
                            hiddenInput.setAttribute('type', 'hidden');
                            hiddenInput.setAttribute('name', selectedSection + ':' + currentItem.name + ':' + fieldKey);
                            hiddenInput.value = 'off';

                            input.addEventListener('input', function () {
                                hiddenInput.disabled = this.checked;
                            });

                            fieldset.appendChild(hiddenInput);

                        } else {
                            input = document.createElement('input');
                            input.setAttribute('id', selectedSection + ':' + currentItem.name + ':' + fieldKey);
                            input.setAttribute('name', selectedSection + ':' + currentItem.name + ':' + fieldKey);
                            input.value = currentItem[fieldKey];
                            if (fieldKey.toLowerCase() === 'password' || fieldKey.toLowerCase() === 'api_key') {
                                input.setAttribute('type', 'password');
                                input.setAttribute('autocomplete', 'new-password');

                                var toggleButton = document.createElement('span');
                                toggleButton.textContent = '👁️';

                                (function (passwordInput, button) {
                                    button.addEventListener('click', function () {
                                        togglePasswordVisibility(passwordInput, button);
                                    });
                                })(input, toggleButton);

                                fieldset.appendChild(toggleButton);
                            } else {
                                input.setAttribute('type', 'text');
                            }
                        }

                        fieldset.appendChild(label);
                        fieldset.appendChild(input);
                        fieldset.appendChild(document.createElement('br'));
                    }
                }

                selectedSectionDiv.appendChild(fieldset);
            }

            // Zeige den ausgewählten Abschnitt
            selectedSectionDiv.style.display = 'block';
        }
    }

    function togglePasswordVisibility(passwordInput, toggleButton) {
        console.log("togglePasswordVisibility");
        console.log(passwordInput.type);
        console.log(passwordInput.name);
        if (passwordInput.type === 'password') {
            passwordInput.type = 'text';
            toggleButton.textContent = '👁️';
        } else {
            passwordInput.type = 'password';
            toggleButton.textContent = '👁️';
        }
    }

    document.getElementById('sendSectionButton').addEventListener('click', function () {
        event.preventDefault();

        var selectedSection = selectedSectionElement.value;

        if (allowedSections.includes(selectedSection)) {
            // Hier können Sie den ausgewählten Abschnittsnamen verwenden
            console.log('Ausgewählter Abschnitt:', selectedSection);

            // Hier rufen Sie die Funktion addConfigEntry auf
            var paramName = selectedSection;  // Verwenden Sie den ausgewählten Abschnitt als paramName
            addConfigEntry(paramName);
        } else {
            console.error('Ungültiger Abschnitt:', selectedSection);
        }
    });

    document.getElementById('meinFormular').addEventListener('submit', function (event) {
        event.preventDefault();

        var formData = new FormData(event.target);

        sendeFormular(formData).then(function () {
            console.log('Formular wurde erfolgreich gesendet und Server ist wieder online.');
            showNotification('Formular wurde erfolgreich gesendet und Server ist wieder online.', 'green');
        }).catch(function (error) {
            console.error('Fehler beim Server-Vorgang:', error);
            showNotification('Es ist ein Fehler aufgetreten. Bitte versuche es erneut.', 'red');
        });
    });

    function sendeFormular(formData) {
        return new Promise(function (resolve, reject) {
            fetch('/save_config', {
                method: 'POST',
                body: formData
            })
                .then(function (response) {
                    if (!response.ok) {
                        reject('Fehlerhafte Serverantwort');
                    }
                    return response.json();
                })
                .then(function (responseData) {
                    resolve(responseData);
                })
                .catch(function (error) {
                    reject(error);
                });
        });
    }

    function waitUntilServerOnline(responseData) {
        // Führe eine GET-Anfrage an die "/check_is_online"-Route durch
        fetch('/check_is_online')
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('Fehlerhafte Serverantwort');
                }
                return response.text();
            })
            .then(function (status) {
                // Überprüfe den Status, ob der Server "OK" ist
                if (status === 'OK') {
                    // Wenn der Status "OK" ist, zeige die grüne Benachrichtigung an
                    showNotification('Formular wurde erfolgreich gesendet und Server ist wieder online.', 'green');
                    // Hier kannst du responseData verwenden
                    console.log('Serverantwort:', responseData);
                } else {
                    // Wenn der Status nicht "OK" ist, warte erneut und überprüfe erneut
                    setTimeout(function () {
                        waitUntilServerOnline(responseData);
                    }, 1000); // Warte 1 Sekunde und überprüfe erneut
                }
            })
            .catch(function (error) {
                console.error('Fehler beim Überprüfen des Serverstatus:', error);
            });
    }

    selectedSectionElement.addEventListener('change', updateSectionFields);

    updateSectionFields();
    var elementWithUseVRM = document.querySelector('[data_name="use_vrm"]');
    if (elementWithUseVRM) {
        var dataNameTarget = elementWithUseVRM.getAttribute('data_name_target');
        enableIpaddressInput(elementWithUseVRM, dataNameTarget);
    }
});
