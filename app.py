import streamlit as st
import pandas as pd
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import networkx as nx


# Step 1: Read Data
@st.cache
def read_data(file_path):
    return pd.read_excel(file_path)


from datetime import timedelta

# Step 2: Assign Journeys
def assign_journeys(sample_data, vehicle_routes_data, num_vans):
    # Create a graph from the vehicle routes data
    G = nx.DiGraph()
    for index, row in vehicle_routes_data.iterrows():
        # Handle the last row to avoid IndexError
        if index < len(vehicle_routes_data) - 1:
            next_row = vehicle_routes_data.iloc[index + 1]
            next_stop = next_row['Postcode']  # Updated to use 'Postcode' instead of 'Stop Postcode'
            G.add_edge(row['Postcode'], next_stop, weight=row['Time to Next Stop'])

    # Initialize the OR-Tools Routing Model
    manager = pywrapcp.RoutingIndexManager(len(G), num_vans, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Define the distance callback for the OR-Tools model
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return G[from_node][to_node]['weight']

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Set the search parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.time_limit.seconds = 10

    # Solve the routing problem
    solution = routing.SolveWithParameters(search_parameters)

    # Extract the assigned journeys
    journeys = {'Index': [], 'Source Surgery': [], 'Source Postcode': [],
                'Date of Specimen': [], 'Time of Specimen': [],
                'Van Collecting': [], 'Time of Collection': []}

    for van_index in range(num_vans):
        index = routing.Start(van_index)
        total_time = timedelta()

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:  # Exclude the depot (SGH Pathology Lab)
                journey_data = sample_data.iloc[node - 1]  # Adjust for 0-based indexing
                journeys['Index'].append(journey_data['Index'])
                journeys['Source Surgery'].append(journey_data['Source Surgery'])
                journeys['Source Postcode'].append(journey_data['Source Postcode'])
                journeys['Date of Specimen'].append(journey_data['Date of Specimen'])
                journeys['Time of Specimen'].append(journey_data['Time of Specimen'])
                journeys['Van Collecting'].append(f'Van {van_index + 1}')

                # Calculate Time of Collection
                time_to_next_stop = timedelta(
                    hours=vehicle_routes_data.iloc[node - 1]['Time to Next Stop'].hour,
                    minutes=vehicle_routes_data.iloc[node - 1]['Time to Next Stop'].minute,
                    seconds=vehicle_routes_data.iloc[node - 1]['Time to Next Stop'].second
                )
                total_time += time_to_next_stop
                journeys['Time of Collection'].append(total_time.total_seconds() / 3600)  # Convert to hours

            index = solution.Value(routing.NextVar(index))

    # Create a DataFrame from the assigned journeys
    assigned_journeys = pd.DataFrame(journeys)

    return assigned_journeys




# Step 3: Update Courier Rounds
def update_courier_rounds(courier_data, optimized_journeys, sample_data):
    for index, row in optimized_journeys.iterrows():
        # Check if the van collecting samples crosses any location with courier rounds
        if row['Source Postcode'] in courier_data['Postcode'].values:
            courier_stop = courier_data[courier_data['Postcode'] == row['Source Postcode']].iloc[0]
            # Check if the courier van has enough space to collect samples
            if courier_stop['Task'] == 'Spare time' or courier_stop['Task'] == 'Deliver/Collect post':
                sample_volume = 0.036  # Volume of one Versapak container
                # Check if there is enough space in the van
                if courier_stop['Volume'] + sample_volume <= 5.3:
                    # Update the courier rounds and remove the journey stop
                    courier_data = courier_data.append({
                        'Round ID': courier_stop['Round ID'],
                        'Vehicle ID': courier_stop['Vehicle ID'],
                        'Time': row['Time of Specimen'],
                        'Location': row['Source Surgery'],
                        'Postcode': row['Source Postcode'],
                        'Task': 'Collect samples',
                        'Volume': sample_volume
                    }, ignore_index=True)
                    optimized_journeys.drop(index, inplace=True)
    return courier_data, optimized_journeys


# Step 4: Calculate Total Time for Journeys
def calculate_total_time(optimized_journeys, vehicle_routes_data):
    total_time = timedelta()

    for _, route_row in optimized_journeys.iterrows():
        time_to_next_stop = timedelta(
            hours=route_row['Time to Next Stop'].hour,
            minutes=route_row['Time to Next Stop'].minute,
            seconds=route_row['Time to Next Stop'].second
        )

        total_time += time_to_next_stop

    return total_time

# Main Streamlit App
def main():
    st.title("Logistics Optimization App")
    st.sidebar.header("Upload Files")

    # Upload Pathology Sample Data
    st.sidebar.subheader("1. Upload Pathology Sample Data")
    sample_file = st.sidebar.file_uploader("Choose a pathology sample file", key="pathology_sample", type=["xlsx"])

    # Upload Vehicle Routes Data
    st.sidebar.subheader("2. Upload Vehicle Routes Data")
    vehicle_routes_file = st.sidebar.file_uploader("Choose a vehicle routes file", key="vehicle_routes", type=["xlsx"])

    # Upload Courier Rounds Data
    st.sidebar.subheader("3. Upload Courier Rounds Data")
    courier_rounds_file = st.sidebar.file_uploader("Choose a courier rounds file", key="courier_rounds", type=["xlsx"])

    if sample_file and vehicle_routes_file and courier_rounds_file:
        sample_data = read_data(sample_file)
        vehicle_routes_data = read_data(vehicle_routes_file)
        courier_data = read_data(courier_rounds_file)

        # Display Sample Data
        st.subheader("Pathology Sample Data")
        st.write(sample_data)

        # Display Routes Data
        st.subheader("Vehicle Routes Data")
        st.write(vehicle_routes_data)

        # Display Courier Rounds Data
        st.subheader("Courier Rounds Data")
        st.write(courier_data)

        # Number of Vans
        num_vans = st.sidebar.number_input("Number of Vans", min_value=1, value=3)

        # Assign Journeys
        if st.sidebar.button("Generate Journeys"):
            # Assign Journeys to Vans
            optimized_journeys = assign_journeys(sample_data, vehicle_routes_data, num_vans)
            st.success("Journeys assigned successfully!")

            # Save the optimized journeys to CSV
            optimized_journeys.to_csv('journey.csv', index=False)

            # Display Assigned Journeys
            st.subheader("Assigned Journeys")
            st.write(optimized_journeys)

            # Update Courier Rounds
            courier_data, optimized_journeys = update_courier_rounds(courier_data, optimized_journeys, sample_data)

            # Save the updated courier rounds to CSV
            courier_data.to_csv('courier_rounds_updated.csv', index=False)

            # Display Updated Courier Rounds
            st.subheader("Updated Courier Rounds")
            st.write(courier_data)

            # Calculate Total Time for Journeys
            total_time = calculate_total_time(optimized_journeys, vehicle_routes_data)
            st.subheader("Total Time for Journeys")
            st.write(f"{total_time} minutes")


if __name__ == "__main__":
    main()
