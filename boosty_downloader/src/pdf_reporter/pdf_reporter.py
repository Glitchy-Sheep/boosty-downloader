"""Module for generating PDF reports with text and image blocks"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from reportlab import platypus
from reportlab.lib import utils
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, Paragraph, SimpleDocTemplate, Spacer

if TYPE_CHECKING:
    from reportlab.pdfbase.ttfonts import TTFont


@dataclass
class NormalText:
    """Textual element, which can be added to the pdf"""

    text: str


@dataclass
class HyperlinkText:
    """Hyperlink element, which can be added to the pdf"""

    text: str
    url: str


class PDFReport:
    """
    Representation of the document, which can be saved to the file

    You must register font before using it:

    ```python
    pdfmetrics.registerFont(font)
    ```

    You can add text/links/images to the document, they will be added one after another.
    """

    def __init__(
        self,
        font: TTFont,
        filename: str,
        margin: int,
        page_format: tuple[float, float],
    ) -> None:
        self.font = font
        self.document_template = SimpleDocTemplate(
            filename,
            pagesize=page_format,
            leftMargin=margin * mm,
            rightMargin=margin * mm,
            topMargin=margin * mm,
            bottomMargin=margin * mm,
        )
        self.elements: list[Flowable] = []

        self.styles = getSampleStyleSheet()
        self.styles['Normal'].fontName = font.fontName

    def add_text(self, text: NormalText) -> None:
        """Add a text to the report right after the last added element"""
        paragraph = Paragraph(text.text, self.styles['Normal'])
        self.elements.append(paragraph)
        self.elements.append(Spacer(1, 5 * mm))  # Добавляем немного пространства

    def add_image(self, image_path: str, width: int = 200) -> None:
        """
        Add an image to the report right after the last added element

        - width 200 is usually enough for full A4 page width.
        """
        img = utils.ImageReader(image_path)
        iw, ih = img.getSize()
        aspect = ih / iw
        new_height = width * aspect
        image = Image(image_path, width=width * mm, height=new_height * mm)
        self.elements.append(image)
        self.elements.append(Spacer(1, 5 * mm))  # Добавляем немного пространства

    def add_link(self, url: str, text: str) -> None:
        """Add a link to the report right after the last added element"""
        address = (
            '<font color="blue"><link href="' + url + '">' + text + '</link></font>'
        )
        self.elements.append(
            platypus.Paragraph(
                address,
                self.styles['Normal'],
            ),
        )

    def add_multitext(self, parts: list[NormalText | HyperlinkText]) -> None:
        formatted_text = ''
        for part in parts:
            if isinstance(part, NormalText):
                formatted_text += part.text
            else:
                formatted_text += f'<font color="blue"><link href="{part.url}">{part.text}</link></font>'
        paragraph = Paragraph(formatted_text, self.styles['Normal'])
        self.elements.append(paragraph)
        self.elements.append(Spacer(1, 5 * mm))

    def save(self) -> None:
        """Save the whole document to the file"""
        self.document_template.build(self.elements)
