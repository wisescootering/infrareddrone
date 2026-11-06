BUTTON_STYLE = """
QPushButton {
    background-color: #17365D;
    color: white;
    font-weight: bold;
    padding: 8px;
    border: 1px solid #102840;
    border-radius: 4px;
}

QPushButton:hover {
    background-color: #244A73;
}

QPushButton:pressed {
    background-color: #0F243E;
}

QPushButton:disabled {
    background-color: #B8C2CC;
    color: #666666;
    border: 1px solid #A0AAB4;
}
"""


def colored_button_style(background_color: str, foreground_color: str = "white") -> str:
    return f"""
QPushButton {{
    background-color: {background_color};
    color: {foreground_color};
    font-weight: bold;
    padding: 8px;
    border: 1px solid {background_color};
    border-radius: 4px;
}}

QPushButton:hover {{
    background-color: {background_color};
}}

QPushButton:pressed {{
    background-color: {background_color};
}}

QPushButton:disabled {{
    background-color: #B8C2CC;
    color: #666666;
    border: 1px solid #A0AAB4;
}}
"""
