"""HTML Reporter for generating HTML documents"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from jinja2 import Template

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class NormalText:
    """Textual element, which can be added to the html document"""

    text: str


@dataclass
class HyperlinkText:
    """Hyperlink element, which can be added to the html document"""

    text: str
    url: str


class TextElement(TypedDict):
    """Text element, which can be added to the html document"""

    type: str
    content: str


class ImageElement(TypedDict):
    """Image element, which can be added to the html document"""

    type: str
    content: str
    width: int


class LinkElement(TypedDict):
    """Link element, which can be added to the html document"""

    type: str
    content: str
    url: str


class HTMLReport:
    """
    Representation of the document, which can be saved as an HTML file.

    You can add text/links/images to the document, they will be added one after another.
    """

    def __init__(self, filename: Path) -> None:
        self.filename = filename
        self.elements: list[TextElement | ImageElement | LinkElement] = []

    def _render_template(self) -> str:
        """Render the HTML document using Jinja2"""
        template = """
        <html>
        <head>
            <title>HTML Report</title>
            <style>
                body {
                    font-family: 'Arial', sans-serif;
                    background-color: #f4f4f9;
                    color: #333;
                    line-height: 1.6;
                    margin: 0;
                    padding: 0;
                    max-width: 90%; /* Increased responsiveness */
                    width: 950px;
                    margin-left: auto;
                    margin-right: auto;
                }
                .content {
                    padding: 2rem; /* Changed to rem for better scaling */
                    background-color: #fff;
                    box-shadow: 0 0 12px rgba(0, 0, 0, 0.1);
                    margin-bottom: 3rem; /* Adjusted for better spacing */
                    margin-top: 1.5rem; /* Adjusted for consistency */
                    border-radius: 8px;
                    transition: all 0.3s ease;
                }
                p {
                    font-size: 1.2rem; /* Increased for better readability */
                    margin-bottom: 1.5rem; /* Adjusted for better spacing */
                }
                a {
                    color: #007bff;
                    text-decoration: none;
                    font-weight: bold;
                }
                a:hover {
                    text-decoration: underline;
                }
                img {
                    display: block;
                    max-width: 100%;
                    height: auto;
                    border-radius: 8px;
                    margin: 0 auto;
                    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
                }
                .new-paragraph {
                    margin-top: 2rem; /* Adjusted for better spacing */
                }
            </style>
        </head>
        <body>
            <div class="content">
                {% for element in elements %}
                    {% if element.type == 'text' %}
                        <p>{{ element.content }}</p>
                    {% elif element.type == 'image' %}
                        <div style="text-align: center;">
                            <img src="{{ element.content }}" width="100%">
                        </div>
                    {% elif element.type == 'link' %}
                        <a href="{{ element.url }}" style="color:blue;">{{ element.content }}</a>
                    {% endif %}
                {% endfor %}
            </div>
        </body>
        </html>
        """
        jinja_template = Template(template)
        return jinja_template.render(elements=self.elements)

    def new_paragraph(self) -> None:
        """Add an empty line between elements"""
        # Append a new paragraph using a proper TextElement type
        self.elements.append(TextElement(type='text', content='<br>'))

    def add_text(self, text: NormalText) -> None:
        """Add a text to the report right after the last added element"""
        # Append text content using TextElement
        self.elements.append(TextElement(type='text', content=text.text))

    def add_image(self, image_path: str, width: int = 600) -> None:
        """
        Add an image to the report right after the last added element

        - width 600 is usually enough for most HTML pages
        """
        # Append image content using ImageElement
        self.elements.append(
            ImageElement(type='image', content=image_path, width=width),
        )

    def add_link(self, text: NormalText, url: str) -> None:
        """Add a link to the report right after the last added element"""
        # Append link content using LinkElement
        self.elements.append(LinkElement(type='link', content=text.text, url=url))

    def save(self) -> None:
        """Save the whole document to the file"""
        html_content = self._render_template()
        with self.filename.open('w', encoding='utf-8') as file:
            file.write(html_content)
