from core.config import Config
from core.utils import Utils


class LogReader:
    def __init__(self):
        self.config = Config()
        self.log_file_path = self.config.log_file_path
        self.lines = []
        self.read_log_file()

    def read_log_file(self):
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as log_file:
                lines = log_file.readlines()

                # Suche von hinten nach der Zeile, die mit "started..." endet
                started_line_index = None
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip().endswith("started..."):
                        started_line_index = i
                        break

                if started_line_index is not None:
                    # Lese alle Zeilen ab der gefundenen Zeile bis zum Ende der Datei
                    last_lines = lines[started_line_index:]
                else:
                    # Wenn die Zeile nicht gefunden wurde, lese die gesamte Datei
                    last_lines = lines

                # Append the read lines to the list
                self.lines.extend(last_lines)
        except FileNotFoundError:
            self.lines.extend(["Log file not found."])
        except Exception as e:
            self.lines.extend([f"Error reading log file: {e}"])

    def get_last_lines(self):
        return self.lines

    def get_log_data_for_frontend(self, show_debug=True):
        # Hole die letzten Zeilen aus der Liste
        last_lines = self.get_last_lines()

        # Wandele die Zeilen in HTML-Format um
        html_formatted_lines = []
        for line in last_lines:
            if not show_debug and line.startswith("[D"):
                continue
            colored_line = self.colorize_log_level(line)
            if len(colored_line) == 0:
                continue
            html_formatted_lines.append(colored_line)

        # Return the HTML-formatted result
        return '<br>'.join(html_formatted_lines)

    def colorize_log_level(self, line):
        # Finden Sie das erste '[' und ']'
        start_index = line.find('[')
        end_index = line.find(']')

        # Check that '[' and ']' exist and start_index comes before end_index
        if start_index != -1 and end_index != -1 and start_index < end_index:
            # Extrahieren Sie das erste Zeichen zwischen '[' und ']'
            log_level = line[start_index + 1]

            if line[end_index + 2] == "{":
                return ""

            # Mappe Log-Level auf Farben
            color_mapping = {
                'D': 'cyan',  # Debug
                'I': 'lightgreen',  # Info
                'E': 'red',  # Error
                'W': 'orange',  # Warning
                'C': 'purple'  # Custom
            }

            if log_level in color_mapping:
                colored_line = f'<span style="color:{color_mapping[log_level]}">{line[start_index:end_index + 1]}</span>{line[end_index + 1:]}'
                return colored_line

        # If no coloring is needed, return the line unchanged
        return line
