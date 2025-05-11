import tkinter as tk
from tkinter import ttk
import serial
import threading
import time

SERIAL_PORT = 'COM8'
BAUDRATE = 115200

ser = None
connected = False
lock = threading.Lock()
MOCK_MODE = True  # Set to False when using the real printer
cancelled = False
stepsize = 1 # seconds
toggle_buttons = {}

# ---------- Syringes ----------
syringes = {
    '0': {'name': 'none', 'steps': 0},
    '1': {'name': '10 mL HenkeJect', 'steps': 20927},
    '2': {'name': '5 mL HenkeJect', 'steps': 10800},
    '3': {'name': '2 mL HenkeJect', 'steps': 20003},
}

# Mapping: name <-> id
syringe_name_to_id = {v['name']: k for k, v in syringes.items()}
syringe_id_to_name = {k: v['name'] for k, v in syringes.items()}

# ---------- Pump Control State ----------
pumps = {
    'X': {'flow': 0.0, 'pos': 0.0, 'syringe': '0', 'enabled': True},
    'Y': {'flow': 0.0, 'pos': 0.0, 'syringe': '0', 'enabled': True},
    'Z': {'flow': 0.0, 'pos': 0.0, 'syringe': '0', 'enabled': True},
}

def toggle_pump(axis):
    pumps[axis]['enabled'] = not pumps[axis]['enabled']
    state = "ON" if pumps[axis]['enabled'] else "OFF"
    toggle_buttons[axis].config(text=f"{axis} {state}")
    print(f"[i] {axis} pump turned {state}")

# ---------- Printer Communication ----------
def connect_serial():
    global ser, connected, cancelled
    cancelled = False

    if MOCK_MODE:
        connected = True
        status_label.config(text=f"✓ Mock connected")
        print("[✓] Mock connected to virtual printer")
    else:
        try:
            ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
            time.sleep(2)
            ser.reset_input_buffer()
            connected = True
            status_label.config(text=f"✓ Connected to {SERIAL_PORT}")
            print(f"[✓] Connected to printer on {SERIAL_PORT}")

            # Send initialization G-code
            send_gcode(f"M92 X-0 Y-0 Z0")
            send_gcode("M302 S0")
            send_gcode("M211 S0")
            send_gcode("G91")

        except Exception as e:
            connected = False
            status_label.config(text="✗ Connection failed")
            print(f"[X] Could not connect: {e}")

def disconnect_serial():
    global ser, connected
    if not MOCK_MODE and ser:
        ser.close()
        ser = None
    connected = False
    status_label.config(text="Disconnected")
    print("[i] Disconnected from printer.")

def send_gcode(command):
    if connected:
        if not MOCK_MODE and ser:
            ser.write((command + '\n').encode())
        print(f">> {command}")

# ---------- Scheduler Thread ----------
def scheduler():
    printer_stepsize = stepsize / 60 ## convert timestep (s) to minutes
    global cancelled
    while True:
        time.sleep(stepsize)
        with lock:
            if connected and not cancelled:
                cmd = "G1"
                for axis, data in pumps.items():
                    if not data.get('enabled', True):
                        continue  # Skip disabled pumps
                    flow = data['flow']
                    printer_flow = (flow / 60) / 1000  # uL/min → mL/sec
                    cmd += f" {axis}{printer_flow}"

                cmd += f" F{printer_stepsize}"
                send_gcode(cmd)

def cancel_and_reset():
    global cancelled
    with lock:
        cancelled = True
        for axis in ['X', 'Y', 'Z']:
            pumps[axis]['flow'] = 0.0
            current_labels[axis].config(text="0.00")
        send_gcode("M112")  # Emergency stop
        send_gcode("M999")  # Firmware reset
        status_label.config(text="✗ Cancelled & Reset")
        print("[!] Cancelled all commands and sent reset.")

# ---------- GUI ----------
def apply_rates():
    with lock:
        # Update flow rates and syringe types
        for axis in ['X', 'Y', 'Z']:
            try:
                new_flow = float(flow_entries[axis].get())
            except ValueError:
                new_flow = 0.0
            pumps[axis]['flow'] = new_flow
            selected_name = syringe_vars[axis].get()
            pumps[axis]['syringe'] = syringe_name_to_id.get(selected_name, '0')
            current_labels[axis].config(text=f"{new_flow:.2f}")

        # Build dynamic M92 command from syringe step sizes
        m92_parts = []
        for axis in ['X', 'Y', 'Z']:
            syringe_id = pumps[axis]['syringe']
            steps_per_ml = syringes[syringe_id]['steps']
            # Use negative steps for X and Y (fluid delivery direction)
            if axis in ['X', 'Y']:
                steps_per_ml = -abs(steps_per_ml)
            m92_parts.append(f"{axis}{steps_per_ml}")
        m92_cmd = "M92 " + " ".join(m92_parts)
        send_gcode(m92_cmd)

        # Optional: re-send these too, just to be safe
        send_gcode("M302 S0")  # Allow cold extrusion
        send_gcode("M211 S0")  # Disable endstops
        send_gcode("G91")      # Relative positioning


# GUI Setup
root = tk.Tk()
root.title("Ender3 Syringe Pump Control")
root.geometry("520x250")

flow_entries = {}
current_labels = {}
syringe_vars = {}
syringe_menus = {}

# Header row for labels
ttk.Label(root, text="Pump").grid(row=0, column=0)
ttk.Label(root, text="Current (uL/min)").grid(row=0, column=1)
ttk.Label(root, text="Set Flow").grid(row=0, column=2)
ttk.Label(root, text="Syringe Type").grid(row=0, column=3)
ttk.Label(root, text="Enable").grid(row=0, column=4)

for i, axis in enumerate(['X', 'Y', 'Z']):
    row = i + 1  # offset by 1 due to header
    ttk.Label(root, text=f"{axis}").grid(row=row, column=0, padx=5, pady=5)

    current_labels[axis] = ttk.Label(root, text="0.00")
    current_labels[axis].grid(row=row, column=1)

    flow_entries[axis] = ttk.Entry(root, width=10)
    flow_entries[axis].insert(0, "0.0")
    flow_entries[axis].grid(row=row, column=2)

    syringe_vars[axis] = tk.StringVar()
    syringe_vars[axis].set(syringes['0']['name'])

    syringe_menu = ttk.OptionMenu(
        root,
        syringe_vars[axis],
        syringes['0']['name'],
        *[v['name'] for v in syringes.values()]
    )
    syringe_menus[axis] = syringe_menu
    syringe_menu.grid(row=row, column=3)

    toggle_buttons[axis] = ttk.Button(root, text=f"{axis} ON", command=lambda a=axis: toggle_pump(a))
    toggle_buttons[axis].grid(row=row, column=4)

ttk.Button(root, text="Set Flow Rates", command=apply_rates).grid(row=5, column=0, columnspan=4, pady=10)

ttk.Button(root, text="Connect", command=connect_serial).grid(row=6, column=0, pady=5)
ttk.Button(root, text="Disconnect", command=disconnect_serial).grid(row=6, column=1, pady=5)
ttk.Button(root, text="Cancel & Reset", command=cancel_and_reset).grid(row=7, column=0, columnspan=4, pady=10)


status_label = ttk.Label(root, text="Disconnected")
status_label.grid(row=6, column=2, columnspan=2)

# Start scheduler thread once
threading.Thread(target=scheduler, daemon=True).start()

root.mainloop()
