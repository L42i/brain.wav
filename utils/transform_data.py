import numpy as np
import pandas as pd

FILE = ''
WINDOW_SIZE = 30

data = np.genfromtxt(FILE, delimiter=',')
df = pd.DataFrame(data)

corr = df.rolling(window=WINDOW_SIZE).corr()