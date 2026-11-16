//! Retro-futurist colour palette, borrowed from the homelab's "reze" web theme:
//! a near-black teal base with neon teal + neon pink accents and lavender text.

use ratatui::style::{Color, Modifier, Style};

// Base surfaces
pub const BG: Color = Color::Rgb(3, 5, 6); // #030506
pub const PANEL: Color = Color::Rgb(11, 17, 19); // #0b1113
pub const SEL_BG: Color = Color::Rgb(21, 40, 43); // selected row wash

// Lines
pub const BORDER: Color = Color::Rgb(36, 58, 61); // #243a3d
pub const BORDER_ACTIVE: Color = Color::Rgb(85, 194, 204); // #55c2cc

// Accents
pub const TEAL: Color = Color::Rgb(85, 194, 204); // #55c2cc — primary
pub const TEAL_DIM: Color = Color::Rgb(111, 154, 158); // #6f9a9e
pub const PINK: Color = Color::Rgb(255, 46, 110); // #ff2e6e — secondary / error
pub const PALE_PINK: Color = Color::Rgb(246, 207, 209); // #f6cfd1 — warn

// Text
pub const TEXT: Color = Color::Rgb(243, 237, 242); // #f3edf2
pub const TEXT_DIM: Color = Color::Rgb(168, 155, 189); // #a89bbd
pub const MUTED: Color = Color::Rgb(92, 85, 112); // #5c5570

// Semantic
pub const SUCCESS: Color = TEAL;
pub const WARN: Color = PALE_PINK;
pub const ERROR: Color = PINK;

/// Spinner frames (braille), animated off the app clock.
pub const SPINNER: [&str; 10] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

pub fn title() -> Style {
    Style::default().fg(BG).bg(TEAL).add_modifier(Modifier::BOLD)
}

pub fn panel_border(active: bool) -> Style {
    Style::default().fg(if active { BORDER_ACTIVE } else { BORDER })
}

pub fn dim() -> Style {
    Style::default().fg(TEXT_DIM)
}

pub fn muted() -> Style {
    Style::default().fg(MUTED)
}

/// A key-cap style for the hint bar: bright key, dim label.
pub fn keycap() -> Style {
    Style::default().fg(TEAL).add_modifier(Modifier::BOLD)
}
