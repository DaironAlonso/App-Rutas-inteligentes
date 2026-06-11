"""
SmartRoute AI Folium Map Generator.
Compiles premium street-level interactive HTML maps using the python folium package.
Supports circular badge icons, route segmentation, and multi-day color coding.
"""
import html
from typing import List, Dict, Any, Optional
import folium

DAY_COLORS = {
    1: "#4f46e5",  # Monday: Indigo
    2: "#0ea5e9",  # Tuesday: Sky Blue
    3: "#10b981",  # Wednesday: Emerald
    4: "#f59e0b",  # Thursday: Amber
    5: "#ec4899",  # Friday: Pink
    6: "#8b5cf6",  # Saturday: Purple
}

DAY_NAMES = {
    1: "Lunes",
    2: "Martes",
    3: "Miércoles",
    4: "Jueves",
    5: "Viernes",
    6: "Sábado",
}

def transport_label(mode: str) -> str:
    if mode == "pie":
        return "A pie"
    if mode == "bus":
        return "Bus"
    return "Carro"

def generate_folium_map(paradas: List[Dict[str, Any]], day_filter: Optional[int] = None) -> str:
    """
    Generates a premium Leaflet map HTML using Folium.
    
    Args:
        paradas: List of route stops
        day_filter: The specific day index (1-6) or None if all days are selected
    """
    # 1. Filter valid stops that have coordinates
    valid_paradas = []
    for p in paradas:
        if p.get("pdv") and p["pdv"].get("latitud") is not None and p["pdv"].get("longitud") is not None:
            valid_paradas.append(p)
            
    if not valid_paradas:
        # Default empty map
        m = folium.Map(location=[4.6097, -74.0817], zoom_start=13)
        return m.get_root().render()

    # Calculate center point
    lats = [p["pdv"]["latitud"] for p in valid_paradas]
    lons = [p["pdv"]["longitud"] for p in valid_paradas]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]

    # 2. Initialize Folium Map
    m = folium.Map(
        location=center,
        zoom_start=13,
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr="OpenStreetMap contributors"
    )

    # 3. Fit bounds if multiple points
    if len(valid_paradas) > 1:
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
        m.fit_bounds(bounds, padding=(30, 30))

    # 4. Generate stop markers & route lines
    day_stop_counters = {}
    for idx, p in enumerate(valid_paradas):
        stop_day = p.get("dia") or day_filter or 1
        day_stop_counters[stop_day] = day_stop_counters.get(stop_day, 0) + 1
        display_idx = day_stop_counters[stop_day] if day_filter is None else (idx + 1)
        
        # Decide marker color
        if day_filter is not None:
            # Single day view: use standard Indigo color
            marker_color = "#4f46e5"
        else:
            # All days view: use color specific to that day of the week
            marker_color = DAY_COLORS.get(stop_day, "#4f46e5")
            
        coord = [p["pdv"]["latitud"], p["pdv"]["longitud"]]
        
        # Escape string values to avoid quotes breaking JS
        pdv_name = html.escape(p["pdv"]["pdv"])
        pdv_dir = html.escape(p["pdv"].get("direccion", "Sin dirección"))
        
        day_label = f" ({DAY_NAMES[stop_day]})" if day_filter is None and stop_day in DAY_NAMES else ""
        
        # Popup HTML Template matching our premium React layout
        popup_html = f"""
        <div style="font-family: 'Inter', sans-serif; font-size: 12px; line-height: 1.4; color: #1e293b; min-width: 180px;">
            <strong style="color: {marker_color}; font-size: 13px;">{pdv_name}{day_label}</strong><br/>
            <hr style="margin: 6px 0; border: 0; border-top: 1px solid #e2e8f0;"/>
            <b>Orden:</b> {display_idx}<br/>
            <b>Llegada:</b> {p.get('horaLlegada', 'N/A')}<br/>
            <b>Salida:</b> {p.get('horaSalida', 'N/A')}<br/>
            <b>Transporte:</b> <span style="color: {'#10b981' if p.get('tipoTransporte') == 'pie' else '#3b82f6'}; font-weight: bold;">{transport_label(p.get('tipoTransporte', 'pie'))}</span><br/>
            <b>Distancia previa:</b> {p.get('distanciaPreviaKm', 0.0):.2f} km ({p.get('tiempoTrasladoMin', 0.0):.0f} min)<br/>
            <b>Dirección:</b> {pdv_dir}
        </div>
        """
        
        # Premium circular marker icon matching React-Leaflet style
        icon_html = f"""
        <div style="
            background-color: {marker_color};
            color: white;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: bold;
            border: 2px solid white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            line-height: 20px;
            text-align: center;
        ">
            {display_idx}
        </div>
        """
        
        folium.Marker(
            location=coord,
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.DivIcon(
                html=icon_html,
                icon_size=(24, 24),
                icon_anchor=(12, 12)
            )
        ).add_to(m)

        # 5. Route Line to previous stop (only connect if they belong to the same day)
        if idx > 0:
            prev_stop = valid_paradas[idx - 1]
            if prev_stop.get("dia") == p.get("dia") or day_filter is not None:
                prev_coord = [prev_stop["pdv"]["latitud"], prev_stop["pdv"]["longitud"]]
                is_pie = p.get("tipoTransporte") == "pie"
                
                # Line styles
                if day_filter is not None:
                    line_color = "#10b981" if is_pie else "#4f46e5"
                else:
                    line_color = DAY_COLORS.get(stop_day, "#4f46e5")
                    
                line_weight = 5 if is_pie else 4
                line_opacity = 0.85 if is_pie else 0.8
                dash = "5, 10" if is_pie else None
                
                # Geometry check from OSRM
                geom = p.get("geometry")
                if geom and geom.get("coordinates"):
                    # Coordinates are [lon, lat] from OSRM, need to flip to [lat, lon]
                    lat_lngs = [[c[1], c[0]] for c in geom["coordinates"]]
                    folium.PolyLine(
                        locations=lat_lngs,
                        color=line_color,
                        weight=line_weight,
                        opacity=line_opacity,
                        dash_array=dash
                    ).add_to(m)
                else:
                    # Fallback to straight line
                    folium.PolyLine(
                        locations=[prev_coord, coord],
                        color=line_color,
                        weight=line_weight - 1,
                        opacity=0.7,
                        dash_array=dash
                    ).add_to(m)

    # 6. Add legend dynamically based on mode
    legend_html = f"""
    <div style="
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 1000;
        background-color: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(4px);
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid #cbd5e1;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        color: #334155;
        font-weight: 600;
        line-height: 1.6;
    ">
        <div style="font-size: 12px; font-weight: bold; margin-bottom: 6px; color: #1e293b; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">Leyenda de Ruta</div>
    """
    
    if day_filter is not None:
        legend_html += """
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
            <span style="display: inline-block; width: 24px; border-top: 4px dashed #10b981;"></span>
            <span>Tramo A Pie</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display: inline-block; width: 24px; border-top: 4px solid #4f46e5;"></span>
            <span>Tramo Vehículo</span>
        </div>
        """
    else:
        # All days legend
        for d in sorted(DAY_NAMES.keys()):
            color = DAY_COLORS[d]
            name = DAY_NAMES[d]
            legend_html += f"""
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background-color: {color}; border: 1px solid white; box-shadow: 0 1px 2px rgba(0,0,0,0.2);"></span>
                <span>{name}</span>
            </div>
            """
            
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

    return m.get_root().render()
