import pypsa
import pandas as pd
import matplotlib.pyplot as plt
import numpy  as np
import cartopy.crs as ccrs
import math
import matplotlib.ticker as mticker
import folium
import time 
import paho.mqtt.client as mqtt
import json
import grid

network = grid.create_network()

# MQTT broker details
broker_address = "mqtt.iammeter.com"  # MQTT broker address - iammeter broker in this case
broker_port = 1883  # Default MQTT port
username = "karuna"
password = "232794"

TOTAL_BLOCKS = 1

PHYSICS = 0

# Topics to subscribe to, for each meter
Topic = {PHYSICS: "device/CD0FF6AB/realtime"}

# set a counter to count the number of messages received
counter = 0

# set the power factor of 0.95
PF = 0.95
tan_phi = math.sqrt(1-PF**2)/PF

# initialize the variables to store the total power for each block
physics_meter_total_power = 1000


# Callback function to handle incoming messages
def on_message(client, userdata, message):
    # decode the message into a python string and then convert to a dictionary  
    Payload_str = message.payload.decode("utf-8")
    payload_dict = json.loads(Payload_str)

    # get the active powers of all three phases
    pa = int(payload_dict['Datas'][0][2])
    pb = int(payload_dict['Datas'][1][2])
    pc = int(payload_dict['Datas'][2][2])
    total_power = pa+pb+pc

    # store the total power to the variables of corresponding blocks
    global physics_meter_total_power

    if message.topic == Topic[PHYSICS]:
        physics_meter_total_power = total_power

    # perform the load flow and plot the network only after receiving messages 
    # containing data from all the meters
    # once the messages from all the meters are received, the counter is reset to 
    # 0 and the network is plotted
    global counter
    counter = counter+1
    if counter==TOTAL_BLOCKS:
        # replace the active powers of the loads with the values received from the meters
        network.loads.loc['Load16', 'p_set'] = physics_meter_total_power/1e6
 
        
        # calculate reactive powers assuming PF = 0.95 and
        # replace the reactive powers of the loads with the values received from the meters
        network.loads.loc['Load16', 'q_set'] = (physics_meter_total_power/1e6)*tan_phi
    
        # check for network consistency
        network.consistency_check()
        
        # perform newton Raphson Load Flow
        network.pf()

        ####################################################################
        ######################### Network Plotting #########################
        ####################################################################
        
        # create a map object
        map = folium.Map(location=(27.619013147338894, 85.5387356168638), 
                         zoom_start=17, max_zoom=30)
    
        # add a layer to plot the distribution grid
        grid_layer = folium.FeatureGroup(name='Grid Layer').add_to(map)
    
        # get coordinates of all the buses in the network
        bus_coords = []
        for index, row in network.buses.iterrows():
        #     first latitude then longitude as folium expects location in this order
            bus_coords.append([row['y'], row['x']])
    
    
        # add circles to the locations of buses in the map
        for i in range(len(bus_coords)):
            # get the bus name
            bus_name = network.buses.index.to_list()[i]
            # get per unit voltage magnitude the bus
            v_mag_pu = network.buses_t.v_mag_pu.iloc[0, i]
            # get voltage angle of the bus (in radian by default) and convert it to degree
            v_ang_rad = network.buses_t.v_ang.iloc[0, i]
            v_ang_deg = (180/math.pi)*v_ang_rad 
            # set bus color based on voltage magnitude
            bus_color=''
            if v_mag_pu<0.95:
                bus_color='red'
            elif 0.95<=v_mag_pu<=1.05:
                bus_color='green'
            else:
                bus_color='yellow'
            # show bus voltage magnitude and voltage angle on the popup 
            popup_text = f'<span style="font-weight:bold; padding-left:20px;">{bus_name}</span><br>|V| = {v_mag_pu: .3f} p.u.<br>δ = {v_ang_deg: .3f} deg'
            folium.Circle(location=bus_coords[i], radius=3.5, 
                          stroke=False,
                         fill=True, fill_color= bus_color, fill_opacity=1.0,
                         popup=folium.Popup(popup_text, max_width=100)).add_to(grid_layer)
    
    
        # add lines
        for index, row in network.lines.iterrows():
            # get the name of the line
            line_name = index
            # get active and reactive powers of the line
            line_p = network.lines_t.p0.loc['now', index ]
            line_q = network.lines_t.q0.loc['now', index ]    
            # get the starting and ending buses of each line
            bus0 = row['bus0']
            bus1 = row['bus1']
            # set line colors based on the line loading# assume nominal line apparent capacity as 0.4 MVA
            s_nom_assumed = 0.069   #assumed nominal capacity of the line (230*300/1000000 MVA)
            # calculate percentage loading of the line
            percentage_loading = (abs(network.lines_t.p0.loc['now', index ])/s_nom_assumed)*100
            line_color = ''
            if percentage_loading <= 50:
               # green color if line loading is less than 50%
               line_color = 'green' 
            elif (50 < percentage_loading <= 100):
                # violet if line loading is between 50 to 100%
               line_color = 'orange' 
            else:
                # red if line loading is greater than 100%
               line_color = 'red'
    
            # tooltip text for the line
            tooltip_text = f'<span style="font-weight: bold; padding-left: 0px">{line_name}</span><br>P = {line_p: .3f} MW<br>Q = {line_q:.3f} MVAr<br>loading = {percentage_loading: .3f}%'
            # now, finally add the line
            # latitude first then longitude
            folium.PolyLine(locations=[(network.buses.loc[bus0].y, network.buses.loc[bus0].x), 
                                      (network.buses.loc[bus1].y, network.buses.loc[bus1].x)],
                            color = line_color,
                           tooltip= tooltip_text).add_to(grid_layer)
    
        # add line between HVB and LVB1 as PyPSA doesn't create a line between the buses if there is a transformer in between
        folium.PolyLine(locations=[(network.buses.loc['HVB'].y, network.buses.loc['HVB'].x), 
                                      (network.buses.loc['LVB1'].y, network.buses.loc['LVB1'].x)],
                                  color = 'black').add_to(grid_layer)
    
        folium.LayerControl().add_to(map)
    
        # Define a legend for the buses
        bus_legend_html = """
             <div style="position: fixed; 
             top: 300px; right: 50px; width: 150px; height: 180px; 
             border:0px solid grey; z-index:9999; font-size:14px;
             background-color: white;
             ">&nbsp; <span style="font-weight: bold; font-size: 20px">Bus Legends </span></b><br>
             &nbsp; <font color="red" style="font-size: 30px;">●</font><span style="font-weight:bold;"> |V| < 0.95</span>   <br>
             &nbsp; <font color="green" style="font-size: 30px;">●</font><span style="font-weight:bold;"> 0.95 ≤ |V| ≤ 1.05</span><br>
             &nbsp; <font color="yellow" style="font-size: 30px;">●</font><span style="font-weight:bold;"> 1.05 < |V|</span><br>
              </div>
             """
    
        # Define a legend for the lines
        line_legend_html = """
             <div style="position: fixed; 
             bottom: 20px; right: 20px; width: 200px; height: 180px; 
             border:0px solid grey; z-index:9999; font-size:14px;
             background-color: white;
             ">&nbsp; <span style="font-weight: bold; font-size: 20px">Line Legends </span></b><br>
             &nbsp; <font color="green" style="font-size: 30px;">—</font><span style="font-weight:bold;"> Loading ≤ 50%</span><br>
             &nbsp; <font color="orange" style="font-size: 30px;">—</font><span style="font-weight:bold;"> 50% ≤ Loading < 100%</span><br>
             &nbsp; <font color="red" style="font-size: 30px;">—</font><span style="font-weight:bold;"> Loading > 100%</span><br>
              </div>
             """
    
        # Add bus legend to the map
        map.get_root().html.add_child(folium.Element(bus_legend_html))
    
        # Add line legend to the map
        map.get_root().html.add_child(folium.Element(line_legend_html))

        # save the geomap of the network in an html file
        map.save('ku_grid.html')
        
    #     Autorefresh section -- modify the html file so that it autorefreshes every minute
        with open('ku_grid.html', 'r', encoding='utf-8') as f:
            f_contents = f.read()
        
        refreshed_content = f_contents.replace('</head>', '<meta http-equiv="refresh" content="60"></head>')
    
        with open('ku_grid.html', 'w', encoding='utf-8') as f:
            f.write(refreshed_content)
    

# Create MQTT client instance
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

# Set username and password for authentication
client.username_pw_set(username, password)

# Assign callback function to handle incoming messages
client.on_message = on_message

# Connect to MQTT broker
client.connect(broker_address, broker_port)

# Subscribe to the topic
client.subscribe(Topic[PHYSICS])

# Loop to maintain MQTT connection and process incoming messages
client.loop_forever()

