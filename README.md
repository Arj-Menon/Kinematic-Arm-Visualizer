# Kinematic Arm Visualizer

A Python-based desktop application built with PyQt6 and Pandas for managing robotic arm specifications and interactively simulating their 2D kinematic chains. 

This tool serves as both a database manager for robotic arm hardware and a "Sandbox" to visualize forward kinematics, link constraints, and workspace scale.

## ✨ Features

### 📊 Data Management
* **Database Integration:** Reads and writes directly to an Excel backend (`robotic_arms.xlsx`).
* **Clean UI:** Displays a standardized data table (Company, Model, Kinematic Chain, Payload, Weight, Cost, Max Length).
* **Add New Hardware:** Built-in form to append new robotic arms to the database on the fly without duplicating data columns.

### 🤖 Interactive Kinematic Sandbox
* **Rigid Body Physics:** Joints follow strict physical link lengths. Dragging a joint rotates it around its parent using trigonometric constraints (Forward Kinematics).
* **Bottom-Up Architecture:** Total reach is dynamically calculated by summing individual link segments in real-time.
* **Live Editing:** Right-click any link to manually edit its length (e.g., from 100mm to 200mm); the entire downstream kinematic chain automatically updates and shifts.
* **Dynamic Joint Types:** Right-click joints to change their Degrees of Freedom (DOF). The shapes update reactively on the canvas.

### 📐 Visual Nomenclature & Scaling
* **Standardized Shapes:**
  * 🟦 **Yaw (Y):** Square block
  * 🟠 **Pitch (P):** Circle block
  * 🔺 **Roll (R):** Triangle block (oriented outward)
* **Absolute Scaling:** True-to-life zoom and pan. The 100mm scale legend dynamically scales with the viewport to provide an accurate sense of physical size.
* **Auto-adjusting UI:** Joint block sizes scale proportionally to their adjacent links so "micro-links" remain clickable and visible, and text padding prevents clipping.
* **Live Parameter Legend:** Displays a live updating list of link lengths (e.g., L1 = 120mm, L2 = 50mm) right on the screen.

## 🛠️ Prerequisites & Installation

Ensure you have Python 3.8+ installed. You can install the required dependencies using `pip`:

```bash
pip install PyQt6 pandas openpyxl
```

## 🚀 Detailed Usage Guide

### 1. Starting the Application
Launch the app from your terminal:

```bash
python main.py
```

This will open the **Main Database Window**, loading your existing arms from `robotic_arms.xlsx`.

### 2. Managing the Database
* **View Data:** Scroll through the table to see the specs for different robotic arms. The UI standardizes the units to `[Kg]` and `[mm]`.
* **Add a New Arm:** Click the **"Add New Arm"** button. Fill out the pop-up form with the arm's specifications. Upon saving, the data is automatically appended to your Excel file and the table refreshes cleanly.

### 3. Launching the Sandbox
* Select any row in the data table.
* Click **"Launch Visualizer"**.
* A prompt will ask you to confirm or edit the Kinematic Chain (e.g., `Y-P-P-R-P-R`) and an initial Total Length to seed the basic spacing.

### 4. Visualizer Controls & Interactions
Once the sandbox is open, you can interact with the arm using the following mouse controls:

* **Rotate a Joint (Left-Click & Drag):** Click and hold any joint (except the dark-colored, fixed base joint). As you drag your mouse, the joint will swing in a perfect circle around its parent, constrained by the rigid link length. All downstream joints will translate with it as a rigid body.
* **Edit Link Length (Right-Click on Link):** Right-click the line connecting two joints. Enter a new millimeter length. The link will visually scale, the downstream arm will be pushed further out, and the total length display (and L1/L2 parameter legend) will update instantly.
* **Edit Joint Type/ID (Right-Click on Joint):** Right-click any joint block to open the Edit menu. Change the ID number or the Type (Yaw, Pitch, Roll). The block's geometric shape will instantly transform to reflect the new kinematics.
* **Zoom Scene (Mouse Wheel):** Scroll up or down to zoom. The 100mm scale legend in the corner will dynamically resize alongside the robot arm, tying the application to real-world mathematical units rather than arbitrary screen space.

## 📁 Project Structure

* `main.py` - Application entry point.
* `main_window.py` - Handles the data table, Excel saving/loading, column mapping, and the "Add Arm" logic.
* `visualizer_window.py` - Manages the QGraphicsView, interactive zoom logic, and live kinematic legends.
* `graphics_items.py` - Contains the trigonometric math, physical constraint logic, text bounding limits, and custom rendering classes for the Joints and Links.
* `robotic_arms.xlsx` - The local Excel database backend.