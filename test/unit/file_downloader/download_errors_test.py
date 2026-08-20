from boosty_downloader.infrastructure.file_downloader import (
    DownloadError,
    DownloadUnexpectedStatusError,
)


def test_download_error_exposes_message_attribute():
    error = DownloadError(
        message='Download failed',
        file=None,
        resource_url='https://example.com/file.bin',
    )

    assert error.message == 'Download failed'
    assert str(error) == 'Download failed'


def test_unexpected_status_error_exposes_message_attribute():
    error = DownloadUnexpectedStatusError(
        status=400,
        response_message='Bad Request',
        resource_url='https://example.com/video.mp4',
    )

    assert error.message == 'Unexpected status code: 400'
    assert str(error) == 'Unexpected status code: 400'
    assert error.resource_url == 'https://example.com/video.mp4'
