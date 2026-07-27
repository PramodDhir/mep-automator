import streamlit as st
import ezdxf
import pandas as pd
import math
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="Professional HVAC P&ID & CSI BOQ Automator", layout="wide")
st.title("❄️ Advanced HVAC P&ID Schematic & CSI-Format BOQ Automator")
st.markdown("Generate consultant-grade HVAC schematics and CSI MasterFormat Division 23 size-disaggregated BOQ from your design summary.")

# --- SIZING CRITERIA ---
with st.expander("Hydraulic Design & Sizing Criteria", expanded=False):
    col1, col2, col3 = st.columns(3)
    delta_t_f = col1.number_input("Design Delta T (°F)", value=12.0)
    max_vel_fps = col2.number_input("Max Allowable Velocity (fps)", value=8.0)
    default_tr_to_gpm = col3.number_input("GPM per TR Factor", value=2.0)

standard_sizes = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 30.0, 36.0]

def calc_pipe_size(gpm):
    if gpm <= 0: return 0.5
    theoretical_dia = math.sqrt(gpm / (2.448 * max_vel_fps))
    for size in standard_sizes:
        if size >= theoretical_dia: return size
    return standard_sizes[-1]

# --- DXF GRAPHICAL SYMBOL HELPERS ---
def draw_valve(msp, x, y, tag="BFV", layer="VALVES"):
    msp.add_lwpolyline([(x-2, y+1.2), (x+2, y-1.2), (x+2, y+1.2), (x-2, y-1.2), (x-2, y+1.2)], dxfattribs={'layer': layer})
    msp.add_text(tag, dxfattribs={'height': 1.2, 'layer': 'ANNOTATIONS'}).set_placement((x-2.5, y+1.5))

def draw_control_valve(msp, x, y, tag="MCV", layer="VALVES"):
    msp.add_lwpolyline([(x-2, y+1.2), (x+2, y-1.2), (x+2, y+1.2), (x-2, y-1.2), (x-2, y+1.2)], dxfattribs={'layer': layer})
    msp.add_line((x, y+1.2), (x, y+3.5), dxfattribs={'layer': layer})
    msp.add_lwpolyline([(x-1.5, y+3.5), (x+1.5, y+3.5), (x+1.5, y+5), (x-1.5, y+5), (x-1.5, y+3.5)], dxfattribs={'layer': layer})
    msp.add_text(tag, dxfattribs={'height': 1.2, 'layer': 'ANNOTATIONS'}).set_placement((x-2.5, y+5.2))

def draw_strainer(msp, x, y, layer="VALVES"):
    msp.add_circle((x, y), radius=1.5, dxfattribs={'layer': layer})
    msp.add_line((x-1.5, y+1.5), (x+1.5, y-1.5), dxfattribs={'layer': layer})
    msp.add_text("STR", dxfattribs={'height': 1.1, 'layer': 'ANNOTATIONS'}).set_placement((x-2, y+2))

def draw_instrument(msp, x, y, label="PI/TI", layer="INSTRUMENTATION"):
    msp.add_circle((x, y), radius=1.8, dxfattribs={'layer': layer})
    msp.add_text(label, dxfattribs={'height': 1.1, 'layer': 'ANNOTATIONS'}).set_placement((x-2, y+2.2))

# --- FILE UPLOAD WORKFLOW ---
uploaded_file = st.file_uploader("Upload Design Summary Excel Sheet (.xlsx)", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.str.strip()
        
        # --- SMART COLUMN MAPPING ---
        rename_map = {}
        for col in df.columns:
            c_lower = col.lower()
            if 'riser' in c_lower:
                rename_map[col] = 'Riser_ID'
            elif 'floor' in c_lower:
                rename_map[col] = 'Floor'
            elif 'tag' in c_lower or 'ahu' in c_lower or 'equipment' in c_lower:
                rename_map[col] = 'AHU_Tag'
            elif c_lower in ['gpm', 'flow', 'design_gpm', 'flow_gpm']:
                rename_map[col] = 'Design_GPM'
            elif c_lower in ['tr', 'ton', 'tons', 'rt', 'cooling_tr']:
                rename_map[col] = 'TR'
        
        df = df.rename(columns=rename_map)
        
        if 'Design_GPM' not in df.columns and 'TR' in df.columns:
            df['Design_GPM'] = df['TR'] * default_tr_to_gpm
        elif 'TR' not in df.columns and 'Design_GPM' in df.columns:
            df['TR'] = df['Design_GPM'] / default_tr_to_gpm
        elif 'Design_GPM' not in df.columns and 'TR' not in df.columns:
            st.error("❌ Excel sheet must contain either a 'Flow/GPM' column or a 'TR/Tonnage' column.")
            st.stop()

        required_cols = ['Riser_ID', 'Floor', 'AHU_Tag', 'Design_GPM', 'TR']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            st.error(f"❌ Missing required columns: {missing_cols}. Detected columns: {list(df.columns)}")
            st.stop()
            
        st.success("✅ Design Data successfully loaded, mapped, and verified!")
        st.dataframe(df, width='stretch')
    except Exception as e:
        st.error(f"Error reading file. Please ensure it is a valid Excel sheet. Error: {e}")
        st.stop()

    if st.button("Generate Professional P&ID & CSI BOQ", type="primary"):
        with st.spinner("Executing hydraulic calculations, sizing, and building CSI Division 23 BOQ..."):
            
            header_gpm = df['Design_GPM'].sum()
            header_tr = df['TR'].sum()
            header_pipe = calc_pipe_size(header_gpm)
            
            unique_risers = df['Riser_ID'].unique()
            num_risers = len(unique_risers)

            doc = ezdxf.new(dxfversion='R2010')
            msp = doc.modelspace()
            
            # Layers setup
            doc.layers.add("CHWS_PIPE", color=5)       # Blue - Chilled Water Supply
            doc.layers.add("CHWR_PIPE", color=1)       # Red - Chilled Water Return
            doc.layers.add("VALVES", color=3)          # Green - Valves & Fittings
            doc.layers.add("INSTRUMENTATION", color=2) # Yellow - DPT, Gauges, Sensors
            doc.layers.add("AHU_EQUIP", color=7)       # White - Equipment outlines
            doc.layers.add("ANNOTATIONS", color=7)     # White - Text & Tags

            riser_spacing = 180
            floor_height = 55
            riser_offset = 20
            header_offset = 30
            
            header_length = (num_risers * riser_spacing) + 80
            
            # Draw Main Header Pipes
            msp.add_line((0, 0), (header_length, 0), dxfattribs={'layer': 'CHWS_PIPE'})
            msp.add_line((0, -header_offset), (header_length, -header_offset), dxfattribs={'layer': 'CHWR_PIPE'})
            
            # Main Header Isolation Valves Graphics
            draw_valve(msp, 40, 0, "BFV-MAIN", "VALVES")
            draw_valve(msp, 40, -header_offset, "BFV-MAIN", "VALVES")

            msp.add_text(f"MAIN CHWS HEADER: {header_tr:.1f} TR | {header_gpm:.1f} GPM | SIZE: {header_pipe}\" DIA", dxfattribs={'height': 3.5, 'layer': 'ANNOTATIONS'}).set_placement((10, 5))
            msp.add_text(f"MAIN CHWR HEADER: {header_tr:.1f} TR | {header_gpm:.1f} GPM | SIZE: {header_pipe}\" DIA", dxfattribs={'height': 3.5, 'layer': 'ANNOTATIONS'}).set_placement((10, -header_offset - 6))

            # --- CSI-FORMAT BOQ DICTIONARY TRACKING ---
            # Format: {(CSI_Code, Description, Size_Rating, Unit): Quantity}
            boq_dict = {}

            def add_csi_item(csi_code, desc, size_rating, qty, unit="EA"):
                key = (csi_code, desc, size_rating, unit)
                boq_dict[key] = boq_dict.get(key, 0.0) + qty

            # Add Main Header Piping & Valves
            add_csi_item("23 21 13", "Hydronic Piping - Chilled Water Main Header (Supply & Return)", f"{header_pipe}\" Dia", header_length * 2, "ft")
            add_csi_item("23 05 23", "Butterfly Valve (Isolation - Main Header)", f"{header_pipe}\" Size", 2, "EA")

            for i, riser_id in enumerate(unique_risers):
                riser_data = df[df['Riser_ID'] == riser_id].sort_values(by="Floor")
                riser_gpm = riser_data['Design_GPM'].sum()
                riser_tr = riser_data['TR'].sum()
                riser_pipe = calc_pipe_size(riser_gpm)
                
                r_chws_x = (i + 1) * riser_spacing
                r_chwr_x = r_chws_x + riser_offset
                
                max_floor = riser_data['Floor'].max()
                riser_top_y = (max_floor * floor_height) + 25
                
                # Draw Riser Stacks
                msp.add_line((r_chws_x, 0), (r_chws_x, riser_top_y), dxfattribs={'layer': 'CHWS_PIPE'})
                msp.add_line((r_chwr_x, -header_offset), (r_chwr_x, riser_top_y), dxfattribs={'layer': 'CHWR_PIPE'})
                
                add_csi_item("23 21 13", f"Hydronic Piping - Chilled Water Riser {riser_id} (Supply & Return)", f"{riser_pipe}\" Dia", riser_top_y * 2, "ft")
                
                # Riser Isolation Butterfly Valves & DPT Graphics
                draw_valve(msp, r_chws_x, 10, f"BFV-R{riser_id}", "VALVES")
                draw_valve(msp, r_chwr_x, 10, f"BFV-R{riser_id}", "VALVES")
                add_csi_item("23 05 23", f"Butterfly Valve (Isolation - Riser {riser_id} Base)", f"{riser_pipe}\" Size", 2, "EA")
                
                draw_instrument(msp, r_chws_x, riser_top_y - 10, "DPT", "INSTRUMENTATION")
                add_csi_item("23 05 19", f"Differential Pressure Transmitter (DPT) - Riser {riser_id}", f"{riser_pipe}\" Loop", 1, "EA")
                
                msp.add_text(f"RISER {riser_id}: {riser_tr:.1f} TR | {riser_gpm:.1f} GPM | {riser_pipe}\" DIA", dxfattribs={'height': 2.5, 'layer': 'ANNOTATIONS'}).set_placement((r_chws_x - 10, riser_top_y + 4))

                for _, row in riser_data.iterrows():
                    floor_y = row['Floor'] * floor_height
                    ahu_tag = row['AHU_Tag']
                    ahu_gpm = row['Design_GPM']
                    ahu_tr = row['TR']
                    ahu_pipe = calc_pipe_size(ahu_gpm)
                    
                    branch_end_x = r_chwr_x + 65
                    
                    # Branch lines to AHU
                    msp.add_line((r_chws_x, floor_y), (branch_end_x, floor_y), dxfattribs={'layer': 'CHWS_PIPE'})
                    msp.add_line((r_chwr_x, floor_y - 12), (branch_end_x, floor_y - 12), dxfattribs={'layer': 'CHWR_PIPE'})
                    
                    add_csi_item("23 21 13", f"Hydronic Piping - AHU Branch Line ({ahu_tag})", f"{ahu_pipe}\" Dia", 130, "ft")
                    
                    # Add AHU Equipment to CSI BOQ (`23 73 13`)
                    add_csi_item("23 73 13", f"Indoor Central-Station Air-Handling Unit ({ahu_tag})", f"{ahu_tr:.1f} TR / {ahu_gpm:.1f} GPM", 1, "EA")

                    # Graphical Valve & Instrumentation Stations on Branch
                    draw_valve(msp, r_chws_x + 15, floor_y, "BFV", "VALVES")
                    draw_strainer(msp, r_chws_x + 28, floor_y, "VALVES")
                    draw_control_valve(msp, r_chws_x + 42, floor_y, "MCV", "VALVES")
                    draw_instrument(msp, r_chws_x + 55, floor_y + 4, "PI/TI", "INSTRUMENTATION")

                    draw_valve(msp, r_chwr_x + 15, floor_y - 12, "BFV", "VALVES")
                    draw_valve(msp, r_chwr_x + 35, floor_y - 12, "BV", "VALVES")
                    draw_instrument(msp, r_chwr_x + 50, floor_y - 8, "PI/TI", "INSTRUMENTATION")

                    # CSI BOQ Size-wise additions for AHU components
                    add_csi_item("23 05 23", "Butterfly Valve (Isolation - Equipment Drop)", f"{ahu_pipe}\" Size", 2, "EA")
                    add_csi_item("23 21 16", "Y-Strainer with SS Screen", f"{ahu_pipe}\" Size", 1, "EA")
                    add_csi_item("23 09 23", "Motorized 2-Way Control Valve with Actuator", f"{ahu_pipe}\" Size", 1, "EA")
                    add_csi_item("23 05 23", "Manual Hydronic Balancing Valve", f"{ahu_pipe}\" Size", 1, "EA")
                    add_csi_item("23 05 19", "Pressure & Temperature Gauge Assembly (PI/TI Set)", f"{ahu_pipe}\" Size", 2, "SET")

                    # Equipment Tag & Notes
                    msp.add_text(f"EQ: {ahu_tag} | {ahu_tr:.1f} TR | {ahu_gpm:.1f} GPM", dxfattribs={'height': 2.2, 'layer': 'ANNOTATIONS'}).set_placement((branch_end_x + 3, floor_y + 2))
                    msp.add_text(f"Line Size: {ahu_pipe}\" DIA", dxfattribs={'height': 1.6, 'layer': 'ANNOTATIONS'}).set_placement((branch_end_x + 3, floor_y - 4))

            stream = io.StringIO()
            doc.write(stream)
            dxf_data = stream.getvalue()

            # --- BUILD CSI-FORMAT BOQ DATAFRAME ---
            boq_rows = []
            for (csi_code, desc, size_rating, unit), qty in sorted(boq_dict.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
                boq_rows.append({
                    "CSI Section": csi_code,
                    "Item Description": desc,
                    "Size / Rating": size_rating,
                    "Quantity": round(qty, 1) if unit == "ft" else int(qty),
                    "Unit": unit
                })
            
            boq_df = pd.DataFrame(boq_rows)
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                boq_df.to_excel(writer, index=False, sheet_name='CSI_Division_23_BOQ')
            excel_data = excel_buffer.getvalue()

            st.success("🎉 Consultant P&ID Schematic & CSI MasterFormat Division 23 BOQ Generated Successfully!")
            col1, col2 = st.columns(2)
            col1.download_button("📥 Download Consultant P&ID DXF", data=dxf_data, file_name="Consultant_HVAC_PID_Schematic.dxf", mime="image/vnd.dxf")
            col2.download_button("📥 Download CSI-Format Excel BOQ", data=excel_data, file_name="CSI_Division_23_HVAC_BOQ.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            st.subheader("CSI MasterFormat Division 23 Bill of Quantities (BOQ) Preview")
            st.dataframe(boq_df, width='stretch')
else:
    st.info("👆 Please upload your Excel Design Summary (containing design flow rates or tonnage) to generate the consultant P&ID schematic and CSI-format BOQ.")
