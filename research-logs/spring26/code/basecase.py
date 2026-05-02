import pandas as pd

from pyDecision.algorithm import topsis_method

def load_population_data(file_path):
    """
    Load school population data from a CSV file.

    Parameters:
    file_path (str): The path to the CSV file containing school population data.

    Returns:
    pd.DataFrame: A DataFrame containing the school population data.
    """
    try:
        population_data = pd.read_csv(file_path)
        return population_data
    except Exception as e:
        print(f"Error loading school population data: {e}")
        return None

def load_budget_data(file_path):
    """
    Load school budget data from a CSV file.

    Parameters:
    file_path (str): The path to the CSV file containing school budget data.

    Returns:
    pd.DataFrame: A DataFrame containing the school budget data.
    """
    try:
        budget_data = pd.read_csv(file_path)
        return budget_data
    except Exception as e:
        print(f"Error loading school budget data: {e}")
        return None
    
if __name__ == "__main__":
    population_data = load_population_data("../assets/basecase-data-population.csv")
    budget_data = load_budget_data("../assets/basecase-data-budget.csv")

    # if population_data is not None:
    #     print("School Population Data:")
    #     print(population_data.head())
    
    # if budget_data is not None:
    #     print("\nSchool Budget Data:")
    #     print(budget_data.head())

    data = pd.merge(population_data, budget_data, on="High Schools")

    data = data[['High Schools', 'Total Population', 'Total Budget']]

    print("\nMerged Data:")
    print(data)

    # Define criteria and weights
    criteria = ["Total Population", "Total Budget"]
    criterion_types = ["min", "max"]
    weights = [0.45, 0.55]  # Equal weights for population and budget

    # Apply TOPSIS method
    data["Score"] = topsis_method(data[criteria], weights, criterion_types, False, False)

    print("\nSchool Rankings based on TOPSIS:")
    print(data[["High Schools", "Score"]].sort_values(by="Score", ascending=False))