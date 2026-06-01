"""CSS for the allCode Textual shell."""

APP_CSS = """
Screen {
    layout: vertical;
    height: 100%;
    overflow: hidden;
    background: #0b0b0b;
    color: #e7e7e7;
}
#app_frame {
    height: 100%;
    background: #0b0b0b;
}
#hero {
    height: 6;
    padding: 0 0 0 0;
    background: #0b0b0b;
    color: #e7e7e7;
}
#transcript_container {
    height: 1fr;
    overflow: hidden;
    background: #0b0b0b;
}
#transcript {
    height: 1fr;
    padding: 1 2 0 2;
    overflow-y: auto;
    background: #0b0b0b;
    color: #e7e7e7;
}
.transcript-cell {
    margin: 0 0 1 0;
    padding: 0;
    background: #0b0b0b;
}
.user {
    background: #141414;
    color: #e7e7e7;
    padding: 0 1;
}
.assistant, .assistant_stream {
    background: #0b0b0b;
    color: #e7e7e7;
}
.tool, .status, .validation {
    color: #a0a0a0;
}
.error {
    color: #ffb4b4;
}
#status {
    height: 1;
    padding: 0 2;
    background: #0b0b0b;
    color: #8a8a8a;
}
#composer_panel {
    dock: bottom;
    height: auto;
    min-height: 4;
    background: #0b0b0b;
    border-top: solid #343434;
}
#command_palette {
    height: 0;
    min-height: 0;
    max-height: 4;
    padding: 0 2;
    background: #0b0b0b;
    color: #9a9a9a;
}
#input {
    height: 3;
    margin: 0 2 1 2;
    padding: 1 1;
    border: none;
    background: #222222;
    color: #f7f7f7;
}
#input:focus {
    border: none;
    background: #262626;
}
"""
