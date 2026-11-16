//! Rendering for the three screens: Models, Config, Download — plus the header,
//! status line, key-hint footer, toasts and the help overlay.

use ratatui::prelude::*;
use ratatui::widgets::{
    Block, BorderType, Borders, Cell, Clear, Gauge, Paragraph, Row, Table, Wrap,
};

use crate::app::{App, DlField, Screen, ToastKind};
use crate::theme;

pub fn draw(f: &mut Frame, app: &mut App) {
    let area = f.area();

    // Paint the base background across the whole frame.
    f.render_widget(Block::default().style(Style::default().bg(theme::BG)), area);

    // Graceful handling of tiny terminals.
    if area.width < 60 || area.height < 12 {
        let msg = format!(
            "terminal too small\nneed at least 60 × 12\n(now {} × {})",
            area.width, area.height
        );
        f.render_widget(
            Paragraph::new(msg)
                .alignment(Alignment::Center)
                .style(Style::default().fg(theme::PINK)),
            centered_rect(area, area.width.saturating_sub(2), 3),
        );
        return;
    }

    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1), // header
            Constraint::Min(3),    // body
            Constraint::Length(1), // status
            Constraint::Length(1), // key hints
        ])
        .split(area);

    draw_header(f, rows[0], app);
    match app.screen {
        Screen::Models => draw_models(f, rows[1], app),
        Screen::Config => draw_config(f, rows[1], app),
        Screen::Download => draw_download(f, rows[1], app),
    }
    draw_status(f, rows[2], app);
    draw_hints(f, rows[3], app);

    // Overlays, most modal last.
    if let Some(t) = app.live_toast() {
        draw_toast(f, area, &t.text, t.kind);
    }
    if app.confirm_unload {
        draw_modal(
            f,
            area,
            " confirm ",
            theme::WARN,
            vec![
                Line::from(Span::styled(
                    "Unload ALL models from the GPU?",
                    Style::default().fg(theme::TEXT).add_modifier(Modifier::BOLD),
                )),
                Line::from(""),
                Line::from(vec![
                    keycap("y"),
                    Span::styled(" yes      ", theme::dim()),
                    keycap("n"),
                    Span::styled(" / Esc  no", theme::dim()),
                ]),
            ],
        );
    }
    if app.show_help {
        draw_help(f, area);
    }
}

fn draw_header(f: &mut Frame, area: Rect, app: &App) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Min(20), Constraint::Length(28)])
        .split(area);

    // Left: brand chip + tabs.
    let mut left = vec![
        Span::styled(" ◢ MODELCTL ◣ ", theme::title()),
        Span::raw(" "),
    ];
    for (i, label) in ["models", "config", "download"].iter().enumerate() {
        let active = app.screen.index() == i;
        left.push(Span::raw(" "));
        if active {
            left.push(Span::styled(
                format!("▸{label}"),
                Style::default().fg(theme::TEAL).add_modifier(Modifier::BOLD),
            ));
        } else {
            left.push(Span::styled(format!("{}·", i + 1), theme::muted()));
            left.push(Span::styled(label.to_string(), theme::dim()));
        }
    }
    f.render_widget(Paragraph::new(Line::from(left)), cols[0]);

    // Right: spinner (when busy) + host.
    let host = app
        .cfg
        .base_url
        .trim_start_matches("http://")
        .trim_start_matches("https://");
    let mut right = vec![];
    if app.busy {
        right.push(Span::styled(
            format!("{} ", app.spinner()),
            Style::default().fg(theme::PINK),
        ));
    }
    right.push(Span::styled("◈ ", Style::default().fg(theme::TEAL_DIM)));
    right.push(Span::styled(host.to_string(), theme::dim()));
    right.push(Span::raw(" "));
    f.render_widget(
        Paragraph::new(Line::from(right)).alignment(Alignment::Right),
        cols[1],
    );
}

fn panel<'a>(title: &'a str, active: bool) -> Block<'a> {
    Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(theme::panel_border(active))
        .title(Span::styled(
            format!(" {title} "),
            Style::default().fg(theme::TEAL).add_modifier(Modifier::BOLD),
        ))
        .style(Style::default().bg(theme::PANEL))
}

fn draw_models(f: &mut Frame, area: Rect, app: &mut App) {
    let header = Row::new(vec![
        Cell::from(" "),
        Cell::from("MODEL"),
        Cell::from("STATE"),
        Cell::from("CTX"),
        Cell::from("CAPS"),
        Cell::from("TTL"),
    ])
    .style(
        Style::default()
            .fg(theme::TEAL_DIM)
            .add_modifier(Modifier::BOLD),
    )
    .height(1)
    .bottom_margin(1);

    let rows: Vec<Row> = app
        .models
        .iter()
        .map(|m| {
            let run_state = app.run_state(&m.id);
            let (state_txt, state_style) = if m.loaded {
                let label = match run_state {
                    Some(s) if !s.is_empty() && !s.eq_ignore_ascii_case("ready") => {
                        format!("● {s}")
                    }
                    _ => "● loaded".to_string(),
                };
                (
                    label,
                    Style::default().fg(theme::TEAL).add_modifier(Modifier::BOLD),
                )
            } else if matches!(run_state, Some(s) if !s.is_empty() && !s.eq_ignore_ascii_case("ready"))
            {
                (
                    format!("◐ {}", run_state.unwrap()),
                    Style::default().fg(theme::WARN),
                )
            } else {
                ("○ unloaded".to_string(), theme::muted())
            };

            let mut caps = Vec::new();
            if m.vision {
                caps.push("vision");
            }
            if m.tools {
                caps.push("tools");
            }
            let ttl = app
                .ttl_for(&m.id)
                .map(|t| {
                    if t == 0 {
                        "resident".to_string()
                    } else {
                        format!("{t}s")
                    }
                })
                .unwrap_or_else(|| "–".to_string());

            Row::new(vec![
                Cell::from(if m.loaded { "◆" } else { " " })
                    .style(Style::default().fg(theme::TEAL)),
                Cell::from(m.id.clone())
                    .style(Style::default().fg(theme::TEXT).add_modifier(Modifier::BOLD)),
                Cell::from(state_txt).style(state_style),
                Cell::from(fmt_ctx(m.context_length)).style(theme::dim()),
                Cell::from(caps.join(" ")).style(Style::default().fg(theme::TEAL_DIM)),
                Cell::from(ttl).style(theme::muted()),
            ])
            .height(1)
        })
        .collect();

    let widths = [
        Constraint::Length(2),
        Constraint::Percentage(32),
        Constraint::Length(13),
        Constraint::Length(8),
        Constraint::Percentage(22),
        Constraint::Length(10),
    ];

    let title = format!("models · llama-swap ({})", app.models.len());
    let table = Table::new(rows, widths)
        .header(header)
        .block(panel(&title, app.screen == Screen::Models))
        .row_highlight_style(
            Style::default()
                .bg(theme::SEL_BG)
                .fg(theme::TEXT)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol(Span::styled("▎", Style::default().fg(theme::PINK)))
        .column_spacing(1);

    f.render_stateful_widget(table, area, &mut app.table_state);

    if app.models.is_empty() {
        let inner = Rect {
            x: area.x + 2,
            y: area.y + 2,
            width: area.width.saturating_sub(4),
            height: 1,
        };
        let txt = if app.busy {
            "loading models…"
        } else {
            "no models — press r to refresh"
        };
        f.render_widget(Paragraph::new(txt).style(theme::muted()), inner);
    }
}

fn draw_config(f: &mut Frame, area: Rect, app: &App) {
    let body = if app.config_text.is_empty() {
        "loading config.yaml from lab3…".to_string()
    } else {
        app.config_text.clone()
    };
    let active = app.screen == Screen::Config;
    let title = format!("config · {}", app.cfg.remote_config_path);
    let p = Paragraph::new(body)
        .style(Style::default().fg(theme::TEXT))
        .block(panel(&title, active))
        .scroll((app.config_scroll, 0));
    f.render_widget(p, area);
}

fn draw_download(f: &mut Frame, area: Rect, app: &App) {
    let outer = panel("download · Hugging Face → lab3", app.screen == Screen::Download);
    let inner = outer.inner(area);
    f.render_widget(outer, area);

    let rows = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([
            Constraint::Length(3), // repo
            Constraint::Length(3), // file
            Constraint::Length(3), // revision
            Constraint::Length(3), // progress
            Constraint::Min(1),    // message / destination
        ])
        .split(inner);

    draw_field(f, rows[0], "repo id", "owner/name", &app.dl_repo, app.dl_field == DlField::Repo);
    draw_field(f, rows[1], "gguf filename", "model.Q4_K_M.gguf", &app.dl_file, app.dl_field == DlField::File);
    draw_field(f, rows[2], "revision", "main", &app.dl_rev, app.dl_field == DlField::Revision);

    if let Some(dl) = &app.download {
        let (label, color) = if let Some(err) = &dl.error {
            (format!("error · {err}"), theme::ERROR)
        } else if dl.finished {
            (format!("done · {}", fmt_bytes(dl.downloaded)), theme::SUCCESS)
        } else {
            let eta = dl
                .eta_secs()
                .map(|s| format!("  ETA {}", fmt_dur(s)))
                .unwrap_or_default();
            let total = if dl.total > 0 {
                format!(" / {}", fmt_bytes(dl.total))
            } else {
                String::new()
            };
            (
                format!(
                    "{}{}   {}/s{}",
                    fmt_bytes(dl.downloaded),
                    total,
                    fmt_bytes(dl.speed_bps as u64),
                    eta
                ),
                theme::TEAL,
            )
        };
        let gauge = Gauge::default()
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .border_type(BorderType::Rounded)
                    .border_style(theme::panel_border(false))
                    .title(Span::styled(
                        format!(" {} ", dl.filename),
                        Style::default().fg(theme::TEXT_DIM),
                    )),
            )
            .gauge_style(Style::default().fg(color).bg(theme::BG))
            .ratio(dl.fraction())
            .label(Span::styled(
                label,
                Style::default().fg(theme::TEXT).add_modifier(Modifier::BOLD),
            ));
        f.render_widget(gauge, rows[3]);
    } else {
        f.render_widget(
            Paragraph::new("Tab between fields, then Enter to start the download on lab3.")
                .style(theme::muted())
                .block(
                    Block::default()
                        .borders(Borders::ALL)
                        .border_type(BorderType::Rounded)
                        .border_style(theme::panel_border(false)),
                ),
            rows[3],
        );
    }

    let dest = format!(
        "destination · {}/{}",
        app.cfg.models_dir,
        if app.dl_file.is_empty() {
            "<filename>"
        } else {
            &app.dl_file
        }
    );
    f.render_widget(
        Paragraph::new(dest).style(theme::muted()).wrap(Wrap { trim: true }),
        rows[4],
    );
}

fn draw_field(f: &mut Frame, area: Rect, label: &str, placeholder: &str, value: &str, active: bool) {
    let title = Span::styled(
        format!(" {label} "),
        if active {
            Style::default().fg(theme::TEAL).add_modifier(Modifier::BOLD)
        } else {
            theme::dim()
        },
    );
    let content: Line = if value.is_empty() {
        Line::from(Span::styled(placeholder.to_string(), theme::muted()))
    } else {
        let mut spans = vec![Span::styled(
            value.to_string(),
            Style::default().fg(theme::TEXT),
        )];
        if active {
            spans.push(Span::styled("█", Style::default().fg(theme::PINK)));
        }
        Line::from(spans)
    };
    let block = Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(theme::panel_border(active))
        .title(title);
    f.render_widget(Paragraph::new(content).block(block), area);
}

fn draw_status(f: &mut Frame, area: Rect, app: &App) {
    let mut spans = Vec::new();
    if app.busy {
        spans.push(Span::styled(
            format!(" {} ", app.spinner()),
            Style::default().fg(theme::PINK),
        ));
    } else {
        spans.push(Span::styled(" › ", Style::default().fg(theme::TEAL)));
    }
    let style = if app.is_error {
        Style::default().fg(theme::ERROR).add_modifier(Modifier::BOLD)
    } else {
        Style::default().fg(theme::TEAL_DIM)
    };
    spans.push(Span::styled(app.status.clone(), style));
    f.render_widget(
        Paragraph::new(Line::from(spans)).style(Style::default().bg(theme::BG)),
        area,
    );
}

fn draw_hints(f: &mut Frame, area: Rect, app: &App) {
    let hints: &[(&str, &str)] = match app.screen {
        Screen::Models => &[
            ("↑↓", "move"),
            ("l", "load/swap"),
            ("u", "unload"),
            ("r", "refresh"),
            ("2", "config"),
            ("3", "download"),
            ("?", "help"),
            ("q", "quit"),
        ],
        Screen::Config => &[
            ("↑↓", "scroll"),
            ("e", "edit"),
            ("r", "reload"),
            ("1", "models"),
            ("3", "download"),
            ("?", "help"),
            ("q", "quit"),
        ],
        Screen::Download => &[
            ("Tab", "field"),
            ("↵", "start"),
            ("Esc", "back"),
            ("?", "help"),
            ("^C", "quit"),
        ],
    };
    f.render_widget(Paragraph::new(hint_line(hints)), area);
}

fn hint_line(pairs: &[(&str, &str)]) -> Line<'static> {
    let mut spans = vec![Span::raw(" ")];
    for (k, label) in pairs {
        spans.push(Span::styled(k.to_string(), theme::keycap()));
        spans.push(Span::styled(format!(" {label}"), theme::muted()));
        spans.push(Span::styled("   ", theme::muted()));
    }
    Line::from(spans)
}

fn keycap(k: &str) -> Span<'static> {
    Span::styled(k.to_string(), theme::keycap())
}

fn draw_toast(f: &mut Frame, area: Rect, text: &str, kind: ToastKind) {
    let (icon, color) = match kind {
        ToastKind::Success => ("✓", theme::SUCCESS),
        ToastKind::Error => ("✕", theme::ERROR),
        ToastKind::Info => ("•", theme::TEAL_DIM),
    };
    let line = format!("{icon} {text}");
    let w = (line.chars().count() as u16 + 4)
        .min(area.width.saturating_sub(2))
        .max(12);
    let h = 3;
    let rect = Rect {
        x: area.x + area.width.saturating_sub(w + 1),
        y: area.y + 2,
        width: w,
        height: h,
    };
    f.render_widget(Clear, rect);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(color))
        .style(Style::default().bg(theme::PANEL));
    f.render_widget(
        Paragraph::new(Line::from(Span::styled(
            line,
            Style::default().fg(color).add_modifier(Modifier::BOLD),
        )))
        .wrap(Wrap { trim: true })
        .block(block),
        rect,
    );
}

fn draw_help(f: &mut Frame, area: Rect) {
    let rows: Vec<Line> = vec![
        section("global"),
        kv("?", "toggle this help"),
        kv("1 / 2 / 3", "switch to models / config / download"),
        kv("q", "quit  (Ctrl+C anywhere)"),
        Line::from(""),
        section("models"),
        kv("↑ ↓ / j k", "move selection"),
        kv("l / Enter", "load & swap to the selected model"),
        kv("u", "unload all models (frees the GPU)"),
        kv("r", "refresh model list"),
        Line::from(""),
        section("config"),
        kv("↑ ↓ / PgUp PgDn", "scroll config.yaml"),
        kv("e", "edit in $EDITOR (backup + validate + atomic write)"),
        kv("r", "reload from lab3"),
        Line::from(""),
        section("download"),
        kv("Tab / ↑ ↓", "move between fields"),
        kv("Enter", "start the Hugging Face download on lab3"),
        kv("Esc", "back to models"),
    ];
    draw_modal(f, area, " help · keybindings ", theme::TEAL, rows);
}

fn section(name: &str) -> Line<'static> {
    Line::from(Span::styled(
        name.to_uppercase(),
        Style::default().fg(theme::PINK).add_modifier(Modifier::BOLD),
    ))
}

fn kv(keys: &str, desc: &str) -> Line<'static> {
    Line::from(vec![
        Span::styled(format!("  {keys:<16}"), theme::keycap()),
        Span::styled(desc.to_string(), theme::dim()),
    ])
}

fn draw_modal(f: &mut Frame, area: Rect, title: &str, accent: Color, lines: Vec<Line>) {
    let h = (lines.len() as u16 + 2).min(area.height.saturating_sub(2));
    let w = 64.min(area.width.saturating_sub(4));
    let rect = centered_rect(area, w, h);
    f.render_widget(Clear, rect);
    let block = Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(accent))
        .title(Span::styled(
            title.to_string(),
            Style::default().fg(accent).add_modifier(Modifier::BOLD),
        ))
        .style(Style::default().bg(theme::PANEL));
    f.render_widget(
        Paragraph::new(lines).block(block).wrap(Wrap { trim: false }),
        rect,
    );
}

fn centered_rect(area: Rect, w: u16, h: u16) -> Rect {
    let x = area.x + (area.width.saturating_sub(w)) / 2;
    let y = area.y + (area.height.saturating_sub(h)) / 2;
    Rect {
        x,
        y,
        width: w.min(area.width),
        height: h.min(area.height),
    }
}

fn fmt_ctx(n: u64) -> String {
    if n == 0 {
        "–".into()
    } else if n % 1024 == 0 {
        format!("{}K", n / 1024)
    } else {
        format!("{n}")
    }
}

fn fmt_dur(secs: u64) -> String {
    if secs >= 3600 {
        format!("{}h{:02}m", secs / 3600, (secs % 3600) / 60)
    } else if secs >= 60 {
        format!("{}m{:02}s", secs / 60, secs % 60)
    } else {
        format!("{secs}s")
    }
}

pub fn fmt_bytes(n: u64) -> String {
    const UNITS: [&str; 5] = ["B", "KB", "MB", "GB", "TB"];
    let mut v = n as f64;
    let mut u = 0;
    while v >= 1024.0 && u < UNITS.len() - 1 {
        v /= 1024.0;
        u += 1;
    }
    if u == 0 {
        format!("{n} B")
    } else {
        format!("{v:.1} {}", UNITS[u])
    }
}
