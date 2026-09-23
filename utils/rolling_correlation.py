import pandas as pd
import numpy as np

# Load data
icn = pd.read_csv('data/raw/icn.csv', header=None)
timecourses = pd.read_csv('data/raw/timecourses_sz.csv', header=None)

# Parameters
window_size = 30
n_samples = timecourses.shape[0]  # 157
n_nodes = timecourses.shape[1]  # 53
n_windows = n_samples - window_size + 1  # 128 windows

# Calculate rolling correlation matrices
rolling_correlations = []

for i in range(n_windows):
    window = timecourses.iloc[i:i+window_size]
    corr_matrix = window.corr()
    rolling_correlations.append(corr_matrix.values)

# Stack all correlation matrices
# Shape: (n_windows, n_nodes, n_nodes) = (128, 53, 53)
rolling_correlations = np.array(rolling_correlations)

# Group nodes by ICN groups
groups = icn[0].values  # Shape: (53,)
n_groups = len(np.unique(groups))  # 7 groups

# Create a dictionary to store grouped correlations
grouped_data = {g: [] for g in range(n_groups)}

# For each window, extract correlations within each group
for window_idx in range(n_windows):
    corr_matrix = rolling_correlations[window_idx]
    
    for group_id in range(n_groups):
        # Find nodes in this group
        group_nodes = np.where(groups == group_id)[0]
        
        # Extract submatrix for this group
        group_corr = corr_matrix[np.ix_(group_nodes, group_nodes)]
        
        # Flatten the upper triangle (excluding diagonal) to get unique correlations
        n_group_nodes = len(group_nodes)
        if n_group_nodes > 1:
            upper_indices = np.triu_indices(n_group_nodes, k=1)
            group_corr_flat = group_corr[upper_indices]
        else:
            group_corr_flat = np.array([])  # No correlations if only 1 node
        
        grouped_data[group_id].append(group_corr_flat)

# Convert to arrays
for group_id in range(n_groups):
    grouped_data[group_id] = np.array(grouped_data[group_id])

# Print summary
print(f"Number of windows: {n_windows}")
print(f"Number of nodes: {n_nodes}")
print(f"Number of groups: {n_groups}")
print("\nGroup sizes:")
for g in range(n_groups):
    n_nodes_in_group = np.sum(groups == g)
    n_correlations = grouped_data[g].shape[1] if grouped_data[g].shape[1] > 0 else 0
    print(f"  Group {g}: {n_nodes_in_group} nodes, {n_correlations} correlations per window")

print(f"\nRolling correlations shape: {rolling_correlations.shape}")
print(f"Grouped data keys: {list(grouped_data.keys())}")
for g in range(n_groups):
    print(f"  Group {g} shape: {grouped_data[g].shape}")

# Save results as numpy files
np.save('rolling_correlations.npy', rolling_correlations)
np.savez('grouped_correlations.npz', **{f'group_{g}': grouped_data[g] for g in range(n_groups)})

# Save grouped correlations as CSV files
for g in range(n_groups):
    df = pd.DataFrame(grouped_data[g])
    df.to_csv(f'group_{g}_correlations.csv', index=False, header=False)

# Save full rolling correlations as CSV (each window as a separate row with flattened values)
# Flatten each 53x53 correlation matrix to a single row
rolling_corr_flat = rolling_correlations.reshape(n_windows, -1)
pd.DataFrame(rolling_corr_flat).to_csv('rolling_correlations.csv', index=False)

print("\nSaved:")
print("  - rolling_correlations.npy and grouped_correlations.npz")
print("  - rolling_correlations.csv (flattened 53x53 matrices)")
print("  - group_0_correlations.csv through group_6_correlations.csv")
