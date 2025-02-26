"""Module for generating PDF reports with text and image blocks"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab import platypus
from reportlab.lib import utils
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, Paragraph, SimpleDocTemplate, Spacer

# TODO: make this thing more modular and configurable
report_font = TTFont('NotoSans', 'NotoSans-Regular.ttf')
pdfmetrics.registerFont(report_font)  # type: ignore (3rd party library w/o annotations)


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
    Module for generating PDF reports with text and image blocks.

    All the elements are added to the report sequentially one after another.
    """

    def _init_font(self) -> None:
        """Prepare font for the report"""
        self.styles = getSampleStyleSheet()
        self.styles['Normal'].fontName = 'NotoSans'

    def __init__(self, filename: str, margin: int = 20) -> None:
        """Create PDFReporter instance, file will be created after save() call"""
        self._init_font()
        self.filename = filename
        self.margin = margin * mm
        self.elements: list[Flowable] = []
        self.doc = SimpleDocTemplate(
            filename,
            pagesize=A4,
            leftMargin=self.margin,
            rightMargin=self.margin,
            topMargin=self.margin,
            bottomMargin=self.margin,
        )

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
        """Save the whole document using added elements (from add_text and add_image)"""
        self.doc.build(list(self.elements))
