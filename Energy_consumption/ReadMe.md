# ⚡ AEP Energy Consumption Forecasting

![Python](https://img.shields.io/badge/Python-3.9-3776AB?style=flat&logo=python&logoColor=white)
![Sklearn](https://img.shields.io/badge/scikit--learn-F7931E?style=flat&logo=scikit-learn&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-150458?style=flat&logo=pandas&logoColor=white)  

![Status](https://img.shields.io/badge/Status-Completed-success)

## 📖 Project Overview
Accurate energy demand forecasting is vital for utility companies to optimize grid stability and reduce costs. This project builds a time-series regression model to predict hourly energy consumption (in Megawatts) for American Electric Power (AEP).

The solution leverages feature engineering (lags, rolling windows, cyclic encoding) and Ridge Regression to achieve high predictive accuracy.

## 📊 Dataset
* **Source:** AEP Hourly Energy Consumption Data.
* **Target:** `AEP_MW` (Hourly energy demand).
* **Size:** ~120,000 hourly observations (2004-2018).

## 🛠 Methodology

### 1. Feature Engineering
Time-series models require robust features to capture patterns:
* **Lag Features:** Added `lag_1h` and `lag_24h` to capture autocorrelation.
* **Rolling Statistics:** Calculated 24-hour and 7-day rolling means to smooth volatility.
* **Cyclic Encoding:** Transformed `hour`, `day`, `month`, and `weekday` into Sine/Cosine pairs to preserve temporal continuity (e.g., 23:00 is close to 00:00).

### 2. Modeling
* **Split:** Chronological split (Train < 2017, Test >= 2017).
* **Algorithm:** **Ridge Regression** with `GridSearchCV` and `TimeSeriesSplit` for robust hyperparameter tuning.
* **Scaling:** Standard scaling was applied to all features.

---

## 📈 Results

The model demonstrated strong performance on the test set:

| Metric | Score |
| :--- | :---: |
| **R² Score** | **0.963** |
| **MAE** | 334.92 MW |
| **RMSE** | 462 MW |

## 💡 Key Insights
* **Autoregression works:** Immediate past consumption (1 hour ago) is the single strongest predictor.
* **Cyclic features matter:** Encoding time cyclically helps linear models understand seasonality better than raw integers.

**To do**  
Seasonality Insight