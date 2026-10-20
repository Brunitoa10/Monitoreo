"""Reporte ejecutivo en PDF (reportlab + gráficos matplotlib)."""
from __future__ import annotations

import io
from typing import Sequence

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from nemesis.reporting import charts
from nemesis.domain.models import format_duration
from nemesis.reporting.base import ReportDataset, ReportExporter
from nemesis.reporting.formatting import LEVEL_COLOR, LEVEL_LABEL, kpi_rows, minutes, ms, pct, status_label

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
ACCENT = colors.HexColor("#1e3a8a")
LINE = colors.HexColor("#e2e8f0")
ZEBRA = colors.HexColor("#f8fafc")
PAGE_W, PAGE_H = A4
MARGIN = 1.6 * cm
CONTENT_W = PAGE_W - 2 * MARGIN


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=20, textColor=INK, alignment=TA_LEFT, spaceAfter=2),
        "subtitle": ParagraphStyle("s", parent=base["Normal"], fontSize=10, textColor=MUTED, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, textColor=ACCENT, spaceBefore=12, spaceAfter=6),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9, leading=12, textColor=INK),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=7.5, leading=9.5, textColor=INK),
        "muted": ParagraphStyle("m", parent=base["Normal"], fontSize=8, leading=10, textColor=MUTED),
    }


def _image(png: bytes | None, width: float = CONTENT_W):
    if not png:
        return None
    w, h = ImageReader(io.BytesIO(png)).getSize()
    return Image(io.BytesIO(png), width=width, height=width * h / w)


def _table(rows: Sequence[Sequence], widths: Sequence[float], header: bool = True, font: float = 7.5) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), font),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
        style += [("BACKGROUND", (0, i), (-1, i), ZEBRA) for i in range(2, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


class PdfExporter(ReportExporter):
    key = "pdf"
    label = "PDF ejecutivo"
    extension = "pdf"
    mime = "application/pdf"

    def export(self, data: ReportDataset) -> bytes:
        st = _styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                                topMargin=MARGIN, bottomMargin=1.4 * cm, title=data.title, author=data.organization)
        story: list = []
        k = data.kpis

        # ---- portada / resumen
        story += [
            Paragraph(data.title, st["title"]),
            Paragraph(f"{data.organization} · Período: {data.filter.label} · Generado: {data.generated_at:%d/%m/%Y %H:%M}", st["subtitle"]),
        ]
        if data.filter.sites or data.filter.types:
            story.append(Paragraph(
                f"Filtros — Sitios: {', '.join(data.filter.sites) or 'todos'} · Tipos: {', '.join(data.filter.types) or 'todos'}",
                st["muted"]))
        story.append(self._kpi_cards(data, st))
        story.append(Spacer(1, 8))

        # ---- hallazgos y recomendaciones
        story.append(Paragraph("Hallazgos y recomendaciones", st["h2"]))
        if data.insights:
            rows = [["Nivel", "Hallazgo", "Recomendación"]]
            for ins in data.insights:
                color = LEVEL_COLOR[ins.level]
                rows.append([
                    Paragraph(f'<font color="{color}"><b>{LEVEL_LABEL[ins.level]}</b></font>', st["small"]),
                    Paragraph(f"<b>{ins.title}</b><br/>{ins.detail}", st["small"]),
                    Paragraph(ins.recommendation, st["small"]),
                ])
            story.append(_table(rows, [1.8 * cm, CONTENT_W * 0.45, CONTENT_W - 1.8 * cm - CONTENT_W * 0.45]))
        else:
            story.append(Paragraph("Sin hallazgos para el período.", st["body"]))

        # ---- gráficos
        story.append(Paragraph("Disponibilidad", st["h2"]))
        donut = _image(charts.status_donut(k.up_now, k.degraded_now, k.down_now, k.reserved_now), CONTENT_W * 0.55)
        if donut:
            story.append(donut)
        for img in (
            charts.availability_bars(data.by_site, "site", "Disponibilidad por sitio"),
            charts.availability_bars(data.by_type, "type", "Disponibilidad por tipo de equipo"),
            charts.time_series(data.availability_series, "disponibilidad_pct", None, "Evolución de la disponibilidad",
                               "%"),
        ):
            flow = _image(img)
            if flow:
                story += [KeepTogether([flow]), Spacer(1, 6)]

        story.append(Paragraph("Latencia", st["h2"]))
        lat = _image(charts.time_series(data.latency_series, "latencia_prom_ms", "type",
                                        "Latencia promedio por tipo", "ms"))
        if lat:
            story.append(lat)

        # ---- tablas de detalle
        story.append(PageBreak())
        story += self._group_table("Resumen por sitio", data.by_site, "site", "Sitio", st)
        story += self._group_table("Resumen por tipo", data.by_type, "type", "Tipo", st)
        story += self._worst_devices(data.devices, st)
        story += self._audit(data, st)
        story += self._hops(data.hops, st)

        story.append(Spacer(1, 10))
        story.append(Paragraph(
            "Disponibilidad = % de mediciones en que el equipo respondió (Operativo o Degradado). "
            "MTTR = duración promedio de los incidentes cerrados. MTBF = horas-equipo monitoreadas / incidentes. "
            "Saltos: traceroute cuando está disponible; si no, estimación por TTL. Equipos 'Disponible' no cuentan en la disponibilidad.",
            st["muted"]))

        doc.build(story, onFirstPage=self._footer(data), onLaterPages=self._footer(data))
        return buf.getvalue()

    # ------------------------------------------------------------- secciones
    @staticmethod
    def _kpi_cards(data: ReportDataset, st) -> Table:
        k = data.kpis
        cards = [
            ("Disponibilidad", pct(k.availability_pct, 2), "promedio del período"),
            ("Caídos ahora", str(k.down_now), f"{k.degraded_now} degradados"),
            ("Incidentes", str(k.incidents_total), f"MTTR {minutes(k.mttr_min)}"),
            ("Latencia p95", ms(k.latency_p95_ms), f"prom {ms(k.latency_avg_ms)}"),
            ("Tiempo con falla", format_duration((k.downtime_min or 0) * 60), f"{k.devices_with_failures} equipos con fallas"),
        ]
        cells = [[Paragraph(f'<font size="7.5" color="#64748b">{t.upper()}</font><br/>'
                            f'<font size="{16 if len(v) <= 9 else 10}"><b>{v}</b></font><br/>'
                            f'<font size="7" color="#64748b">{s}</font>', st["body"]) for t, v, s in cards]]
        t = Table(cells, colWidths=[CONTENT_W / len(cards)] * len(cards), rowHeights=[1.7 * cm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
            ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        detail = [["Indicador", "Valor"]] + [[a, b] for a, b in kpi_rows(k)]
        wrapper = Table([[t], [Spacer(1, 6)], [_table(detail, [CONTENT_W * 0.65, CONTENT_W * 0.35])]],
                        colWidths=[CONTENT_W])
        wrapper.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        return wrapper

    @staticmethod
    def _group_table(title: str, df: pd.DataFrame, col: str, label: str, st) -> list:
        if df.empty:
            return []
        rows = [[label, "Equipos", "Disponib.", "Lat. prom", "Lat. p95", "Pérdida", "Incid.", "Downtime"]]
        for r in df.itertuples():
            rows.append([getattr(r, col), r.equipos, pct(r.disponibilidad_pct), ms(r.latencia_prom_ms),
                         ms(r.latencia_p95_ms), pct(r.perdida_prom_pct, 1), r.incidentes, minutes(r.downtime_min)])
        w = CONTENT_W
        return [Paragraph(title, st["h2"]),
                _table(rows, [w * .22, w * .09, w * .12, w * .12, w * .12, w * .1, w * .09, w * .14])]

    @staticmethod
    def _worst_devices(df: pd.DataFrame, st) -> list:
        if df.empty:
            return []
        worst = df[df["downtime_min"] > 0].sort_values("downtime_min", ascending=False).head(25)
        title = "Equipos con más tiempo de falla"
        if worst.empty:
            worst, title = df.sort_values("latencia_p95_ms", ascending=False).head(15), "Equipos con mayor latencia"
        rows = [["Equipo", "Tipo", "Sitio", "Estado", "Disponib.", "p95", "Pérdida", "Fallas", "Tiempo con falla"]]
        for r in worst.itertuples():
            rows.append([Paragraph(str(r.equipo), st["small"]), r.tipo, r.sitio, status_label(r.estado_actual),
                         pct(r.disponibilidad_pct), ms(r.latencia_p95_ms), pct(r.perdida_prom_pct, 1),
                         r.incidentes, format_duration(r.downtime_min * 60)])
        w = CONTENT_W
        return [Paragraph(title, st["h2"]),
                _table(rows, [w * .22, w * .1, w * .1, w * .1, w * .1, w * .09, w * .09, w * .07, w * .13])]

    AUDIT_MAX_ROWS = 400

    @classmethod
    def _audit(cls, data: ReportDataset, st) -> list:
        audit, summary = data.audit, data.audit_summary
        out: list = [PageBreak(), Paragraph("Auditoría de fallas", st["h2"])]
        if audit.empty:
            return out + [Paragraph("Sin fallas registradas en el período.", st["body"])]
        out.append(Paragraph(
            f"{len(audit)} fallas registradas. Caída = primer chequeo sin respuesta; Recuperación = primer chequeo OK "
            "posterior; Último OK = último chequeo correcto antes de la caída (el corte ocurrió entre ambos).", st["muted"]))
        out.append(Spacer(1, 4))
        if not summary.empty:
            rows = [["Equipo", "Tipo", "Sitio", "Fallas", "Tiempo total con falla", "Falla más larga", "Última falla"]]
            for r in summary.head(40).to_dict("records"):
                rows.append([Paragraph(str(r["Equipo"]), st["small"]), r["Tipo"], r["Sitio"], r["Fallas"],
                             r["Tiempo total con falla"], r["Falla más larga"], r["Última falla"]])
            w = CONTENT_W
            out += [Paragraph("Resumen por equipo", st["body"]),
                    _table(rows, [w * .24, w * .1, w * .11, w * .07, w * .17, w * .15, w * .16]), Spacer(1, 8)]
        rows = [["N°", "Equipo", "Sitio", "Tipo falla", "Caída", "Recuperación", "Duración", "Estado"]]
        for d in audit.head(cls.AUDIT_MAX_ROWS).to_dict("records"):
            caida = f"{d['Fecha caída']} {d['Hora caída']}"
            rec = f"{d['Fecha recuperación']} {d['Hora recuperación']}".strip() or "—"
            rows.append([d["N°"], Paragraph(str(d["Equipo"]), st["small"]), d["Sitio"], d["Severidad"], caida, rec,
                         Paragraph(str(d["Duración"]), st["small"]), d["Estado"]])
        w = CONTENT_W
        out += [Paragraph("Detalle cronológico", st["body"]),
                _table(rows, [w * .06, w * .22, w * .1, w * .1, w * .15, w * .15, w * .13, w * .09], font=7)]
        if len(audit) > cls.AUDIT_MAX_ROWS:
            out.append(Paragraph(f"Se muestran las {cls.AUDIT_MAX_ROWS} más recientes; el detalle completo está en el Excel.",
                                 st["muted"]))
        return out

    @staticmethod
    def _hops(df: pd.DataFrame, st) -> list:
        if df.empty:
            return []
        df = df.sort_values(["saltos_traceroute", "saltos_estimados_ttl"], ascending=False).head(20)
        rows = [["Equipo", "Tipo", "Sitio", "Saltos (traceroute)", "Saltos (TTL)", "Rutas distintas", "RTT ruta"]]
        for r in df.itertuples():
            def fmt(v):
                return "—" if pd.isna(v) else f"{v:.0f}"
            rows.append([Paragraph(str(r.equipo), st["small"]), r.tipo, r.sitio, fmt(r.saltos_traceroute),
                         fmt(r.saltos_estimados_ttl), fmt(r.rutas_distintas), ms(None if pd.isna(r.rtt_ruta_ms) else r.rtt_ruta_ms)])
        w = CONTENT_W
        return [Paragraph("Saltos de red (top 20)", st["h2"]),
                _table(rows, [w * .28, w * .11, w * .11, w * .14, w * .12, w * .12, w * .12])]

    @staticmethod
    def _footer(data: ReportDataset):
        def draw(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN, 0.8 * cm, f"{data.title} · {data.organization}")
            canvas.drawRightString(PAGE_W - MARGIN, 0.8 * cm, f"Página {doc.page}")
            canvas.setStrokeColor(LINE)
            canvas.line(MARGIN, 1.1 * cm, PAGE_W - MARGIN, 1.1 * cm)
            canvas.restoreState()
        return draw
