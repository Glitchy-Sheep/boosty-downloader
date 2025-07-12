"""HTML Reporter for generating semantic HTML documents with post metadata"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, TypedDict

from jinja2 import Template

if TYPE_CHECKING:
    from pathlib import Path

# Constants
BYTES_IN_KILOBYTE = 1024  # Number of bytes in a kilobyte


def format_file_size(size_bytes: int | None) -> str:
    """Format file size in human-readable format"""
    if size_bytes is None:
        return 'Unknown size'

    if size_bytes == 0:
        return '0 B'

    size_names = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while size_bytes >= BYTES_IN_KILOBYTE and i < len(size_names) - 1:
        size_bytes /= BYTES_IN_KILOBYTE
        i += 1

    return f'{size_bytes:.1f} {size_names[i]}'


@dataclass
class NormalText:
    """Textual element, which can be added to the html document"""

    text: str


@dataclass
class HyperlinkText:
    """Hyperlink element, which can be added to the html document"""

    text: str
    url: str


@dataclass
class PostMetadata:
    """Metadata for a post"""

    title: str
    post_id: str
    created_at: datetime
    updated_at: datetime
    author: str
    original_url: str


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


class SpacerElement(TypedDict):
    """Spacer element for proper spacing between content blocks"""

    type: str


class FileElement(TypedDict):
    """File element for downloadable files"""

    type: str
    filename: str
    title: str
    size: int | None
    url: str
    local_path: str | None


class VideoElement(TypedDict):
    """Video element for video content"""

    type: str
    title: str
    duration: str | None
    size: int | None
    url: str
    local_path: str | None
    video_type: str  # 'boosty' or 'external'


class HTMLReport:
    """
    Representation of the document, which can be saved as a semantic HTML file.

    This class generates modern, semantic HTML with proper metadata, structured data,
    and accessible markup for archival and parsing purposes.
    """

    def __init__(self, filename: Path, metadata: PostMetadata | None = None) -> None:
        self.filename = filename
        self.metadata = metadata
        self.elements: list[TextElement | ImageElement | LinkElement | SpacerElement | FileElement | VideoElement] = []

    def _generate_structured_data(self) -> str:
        """Generate JSON-LD structured data for the post"""
        if not self.metadata:
            return ''

        structured_data = {
            '@context': 'https://schema.org',
            '@type': 'BlogPosting',
            'headline': self.metadata.title,
            'datePublished': self.metadata.created_at.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'dateModified': self.metadata.updated_at.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'author': {
                '@type': 'Person',
                'name': self.metadata.author,
            },
            'url': self.metadata.original_url,
            'identifier': self.metadata.post_id,
            'mainEntityOfPage': {
                '@type': 'WebPage',
                '@id': self.metadata.original_url,
            },
        }

        return json.dumps(structured_data, indent=2, ensure_ascii=False)

    def _render_template(self) -> str:
        """Render the HTML document using Jinja2 with semantic structure"""
        template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>{{ title }}</title>

    <!-- Structured Data -->
    {% if structured_data %}
    <script type="application/ld+json">
{{ structured_data }}
    </script>
    {% endif %}

    <style>
        /* Modern CSS with semantic styling */
        :root {
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --text-color: #2c3e50;
            --text-light: #7f8c8d;
            --background: #f5f6fa;
            --surface: #f8f9fa;
            --border: #e9ecef;
            --link-color: #3498db;
            --link-hover: #2980b9;
            --shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            --radius: 8px;
            --spacing: 1rem;
        }

        @media (prefers-color-scheme: dark) {
            :root {
                --primary-color: #ecf0f1;
                --text-color: #ecf0f1;
                --text-light: #bdc3c7;
                --background: #2c3e50;
                --surface: #34495e;
                --border: #4a5568;
                --link-color: #74b9ff;
                --link-hover: #0984e3;
                --shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            }

            .container {
                background-color: #34495e;
            }

            .post-header {
                background-color: #34495e;
            }
        }

        * {
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
            line-height: 1.6;
            color: var(--text-color);
            background-color: var(--background);
            margin: 0;
            padding: var(--spacing);
        }

        .container {
            max-width: 800px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            overflow: hidden;
        }

        /* Post metadata styles */
        .post-header {
            background-color: #ffffff;
            border-bottom: 1px solid var(--border);
            padding: 1.5rem 2rem;
        }

        .post-title {
            font-size: 1.8rem;
            font-weight: 600;
            margin: 0 0 1rem 0;
            line-height: 1.3;
            color: var(--text-color);
        }

        .post-meta {
            display: flex;
            justify-content: flex-start;
            gap: 1.5rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
            color: var(--text-light);
        }

        .meta-item {
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }

        .meta-item::before {
            content: '•';
            color: var(--text-light);
            font-weight: bold;
        }

        .meta-item:first-child::before {
            content: '';
        }

        .post-link {
            color: var(--link-color);
            text-decoration: none;
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            font-size: 0.8rem;
            word-break: break-all;
            transition: color 0.2s;
        }

        .post-link:hover {
            color: var(--link-hover);
            text-decoration: underline;
        }

        /* Content styles */
        .post-content {
            padding: 2rem;
        }

        .post-content p {
            margin: 0 0 1.5rem 0;
            font-size: 1.1rem;
            line-height: 1.7;
        }

        .post-content p:last-child {
            margin-bottom: 0;
        }

        .content-spacer {
            margin: 2rem 0;
        }

        .post-content a {
            color: var(--link-color);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.2s;
        }

        .post-content a:hover {
            color: var(--link-hover);
            text-decoration: underline;
        }

        /* Image styles */
        .image-container {
            text-align: center;
            margin: 2rem 0;
        }

        .image-container a {
            text-decoration: none;
            border: none;
            outline: none;
        }

        .post-content img {
            max-width: 100%;
            height: auto;
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            transition: transform 0.2s;
            cursor: pointer;
        }

        .post-content img:hover {
            transform: scale(1.02);
        }

        /* File and Video styles */
        .file-container, .video-container {
            margin: 2rem 0;
            padding: 1rem;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            background-color: var(--surface);
        }

        .file-container a, .video-container a {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--link-color);
            text-decoration: none;
            font-weight: 500;
        }

        .file-container a:hover, .video-container a:hover {
            color: var(--link-hover);
            text-decoration: underline;
        }

        .file-icon, .video-icon {
            font-size: 1.2rem;
        }

        .file-meta, .video-meta {
            font-size: 0.9rem;
            color: var(--text-light);
            margin-top: 0.5rem;
        }

        .video-container video {
            width: 100%;
            max-width: 100%;
            height: auto;
            border-radius: var(--radius);
            margin-top: 1rem;
        }

        /* Footer styles */
        .post-footer {
            background-color: var(--border);
            padding: 1.5rem 2rem;
            text-align: center;
            font-size: 0.9rem;
            color: var(--text-light);
            border-top: 1px solid var(--border);
        }

        /* Hidden post ID for parsing */
        .post-id-data {
            display: none;
        }

        /* Responsive design */
        @media (max-width: 768px) {
            body {
                padding: 0.5rem;
            }

            .post-header {
                padding: 1rem 1.5rem;
            }

            .post-title {
                font-size: 1.4rem;
            }

            .post-meta {
                flex-direction: column;
                gap: 0.3rem;
                align-items: flex-start;
            }

            .post-content {
                padding: 1.5rem;
            }

            .post-footer {
                padding: 1rem;
            }
        }
    </style>
</head>
<body>
    <article class="container" itemscope itemtype="https://schema.org/BlogPosting">
        <!-- Hidden post ID for parsing -->
        {% if post_id %}
        <div class="post-id-data" data-post-id="{{ post_id }}">{{ post_id }}</div>
        {% endif %}

        <!-- Post Header with metadata -->
        {% if metadata %}
        <header class="post-header">
            <h1 class="post-title" itemprop="headline">{{ title }}</h1>
            <div class="post-meta">
                <div class="meta-item">
                    <time datetime="{{ created_at_iso }}" itemprop="datePublished">
                        Created: {{ created_at_readable }}
                    </time>
                </div>
                {% if updated_at_iso != created_at_iso %}
                <div class="meta-item">
                    <time datetime="{{ updated_at_iso }}" itemprop="dateModified">
                        Updated: {{ updated_at_readable }}
                    </time>
                </div>
                {% endif %}
                <div class="meta-item">
                    <span itemprop="author" itemscope itemtype="https://schema.org/Person">
                        <span itemprop="name">{{ author }}</span>
                    </span>
                </div>
                <div class="meta-item">
                    <a href="{{ original_url }}" class="post-link" itemprop="url" target="_blank" rel="noopener">
                        {{ original_url }}
                    </a>
                </div>
            </div>
        </header>
        {% endif %}

        <!-- Post Content -->
        <main class="post-content" itemprop="articleBody">
            {% for element in elements %}
                {% if element.type == 'text' %}
                    <p data-content-type="text">{{ element.content }}</p>
                {% elif element.type == 'image' %}
                    <div class="image-container" data-content-type="image">
                        <a href="{{ element.content }}" target="_blank" rel="noopener">
                            <img src="{{ element.content }}" alt="Image from post" loading="lazy">
                        </a>
                    </div>
                {% elif element.type == 'link' %}
                    <p data-content-type="link"><a href="{{ element.url }}" target="_blank" rel="noopener">{{ element.content }}</a></p>
                {% elif element.type == 'file' %}
                    <div class="file-container" data-content-type="file">
                        {% if element.local_path %}
                            <a href="{{ element.local_path }}" download>
                                <span class="file-icon">📄</span>
                                <span>{{ element.title }}</span>
                            </a>
                        {% else %}
                            <a href="{{ element.url }}" target="_blank" rel="noopener">
                                <span class="file-icon">📄</span>
                                <span>{{ element.title }}</span>
                            </a>
                        {% endif %}
                        <div class="file-meta">
                            {% if element.size %}Size: {{ element.size | filesizeformat }}{% endif %}
                            {% if element.filename %}• Filename: {{ element.filename }}{% endif %}
                        </div>
                    </div>
                {% elif element.type == 'video' %}
                    <div class="video-container" data-content-type="video" data-video-type="{{ element.video_type }}">
                        <div class="video-header">
                            <span class="video-icon">🎥</span>
                            <strong>{{ element.title }}</strong>
                        </div>
                        {% if element.local_path %}
                            <video controls>
                                <source src="{{ element.local_path }}" type="video/mp4">
                                Your browser does not support the video tag.
                            </video>
                        {% else %}
                            <p><a href="{{ element.url }}" target="_blank" rel="noopener">Open video: {{ element.title }}</a></p>
                        {% endif %}
                        <div class="video-meta">
                            {% if element.duration %}Duration: {{ element.duration }}{% endif %}
                            {% if element.size %}• Size: {{ element.size | filesizeformat }}{% endif %}
                            • Type: {{ element.video_type | title }}
                        </div>
                    </div>
                {% elif element.type == 'spacer' %}
                    <div class="content-spacer"></div>
                {% endif %}
            {% endfor %}
        </main>

        <!-- Post Footer -->
        <footer class="post-footer">
            <p>
                Archived copy of post from Boosty platform.
                {% if metadata %}
                Saved: {{ save_date }}
                {% endif %}
            </p>
        </footer>
    </article>
</body>
</html>"""

        # Prepare template variables
        template_vars = {
            'elements': self.elements,
            'structured_data': self._generate_structured_data() if self.metadata else '',
            'title': self.metadata.title if self.metadata else 'Boosty Post',
            'post_id': self.metadata.post_id if self.metadata else '',
            'metadata': self.metadata is not None,
            'save_date': datetime.now(timezone.utc).strftime('%d.%m.%Y at %H:%M UTC'),
        }

        if self.metadata:
            template_vars.update({
                'author': self.metadata.author,
                'original_url': self.metadata.original_url,
                'created_at_iso': self.metadata.created_at.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'updated_at_iso': self.metadata.updated_at.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'created_at_readable': self.metadata.created_at.strftime('%d.%m.%Y at %H:%M UTC'),
                'updated_at_readable': self.metadata.updated_at.strftime('%d.%m.%Y at %H:%M UTC'),
            })

        jinja_template = Template(template)
        jinja_template.globals['filesizeformat'] = format_file_size
        return jinja_template.render(**template_vars)

    def add_spacer(self) -> None:
        """Add proper spacing between content blocks using CSS instead of empty paragraphs"""
        self.elements.append(SpacerElement(type='spacer'))

    def add_text(self, text: NormalText) -> None:
        """Add a text paragraph to the report"""
        # Skip empty text blocks to match Boosty frontend behavior
        if text.text.strip():
            self.elements.append(TextElement(type='text', content=text.text))

    def add_image(self, image_path: str, width: int = 600) -> None:
        """Add an image to the report"""
        self.elements.append(
            ImageElement(type='image', content=image_path, width=width),
        )

    def add_link(self, text: NormalText, url: str) -> None:
        """Add a link to the report"""
        self.elements.append(LinkElement(type='link', content=text.text, url=url))

    def add_file(self, filename: str, title: str, url: str, size: int | None = None, local_path: str | None = None) -> None:
        """Add a file to the report"""
        self.elements.append(FileElement(
            type='file',
            filename=filename,
            title=title,
            size=size,
            url=url,
            local_path=local_path,
        ))

    def add_video(self, title: str, url: str, video_type: str, duration: str | None = None, size: int | None = None, local_path: str | None = None) -> None:
        """Add a video to the report"""
        self.elements.append(VideoElement(
            type='video',
            title=title,
            duration=duration,
            size=size,
            url=url,
            local_path=local_path,
            video_type=video_type,
        ))

    def new_paragraph(self) -> None:
        """Add spacing between content blocks (replaces old <br> approach)"""
        self.add_spacer()

    def save(self) -> None:
        """Save the whole document to the file"""
        html_content = self._render_template()
        with self.filename.open('w', encoding='utf-8') as file:
            file.write(html_content)
