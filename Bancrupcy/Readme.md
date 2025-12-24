![Python](https://img.shields.io/badge/Python-3.9-3776AB?style=flat&logo=python&logoColor=white)
![Sklearn](https://img.shields.io/badge/scikit--learn-F7931E?style=flat&logo=scikit-learn&logoColor=white)
![CatBoost](https://img.shields.io/badge/CatBoost-FFB800?style=flat&logo=xgboost&logoColor=white)

![Status](https://img.shields.io/badge/Status-Completed-success)

## 📊 Dataset
* **Source:** Taiwan Economic Journal (1999-2009).
* **Target:** `Bankrupt?` (0 = Healthy, 1 = Bankrupt).
* **Features:** 95 numerical financial ratios (ROA, Debt Ratio, Turnover, etc.).
* **Imbalance:** Only 3.2% of companies are bankrupt. 

[Company Bankruptcy Prediction](https://www.kaggle.com/datasets/fedesoriano/company-bankruptcy-prediction).**

# 📉 Corporate Bankruptcy Prediction & Feature Selection
Goal: Develop a machine learning model to predict company bankruptcy based on 95 financial ratios.

## 📖 Project Overview
Predicting corporate bankruptcy is a high-stakes classification problem characterized by extreme class imbalance. This project focuses on **Feature Selection** strategy: how to reduce 95 financial ratios down to the most critical predictors to improve model performance and interpretability.

Challenge: The dataset is highly imbalanced (only ~3% of companies are bankrupt).  
A naive model predicting "healthy" for everyone would achieve 97% accuracy but fail to identify risk.  
Therefore, we prioritize ROC-AUC, Recall (catching bankruptcies), and F1-Score.

### Feature Selection Strategy
We benchmarked three different approaches to dimensionality reduction:
* **Filter Method (SelectKBest):** Statistical selection (ANOVA). Fast, but ignores feature interactions.
* **Wrapper Method (SFS):** Sequential Forward Selection. Finds interactions, but computationally heavy.
* **Embedded Method (Lasso L1):** Selecting features via regularization coefficients.
    * *Result:* Reduced dimensions from **95 $\to$ 30** features.

## 📈 Key Results

| Strategy | Model | ROC-AUC | Recall |
| :--- | :--- | :---: | :---: |
| **All Features** | Baseline (LogReg) | 0.642 | 0.35 |
| **Filter Selection** | LogReg + KBest (7 feats) | 0.931 | 0.86 |
| **Embedded Selection** | **CatBoost (30 feats)** | **0.954** | **0.47** |

## 💡 Business Conclusion
1.  **Quality over Quantity:** Reducing the dataset from 95 to 30 features drastically improved model stability and performance.
2.  **Top Predictors:** The analysis highlighted **Net Income to Total Assets**, **Debt Ratio**, and **Net Worth/Assets** as the most critical indicators of solvency.
3.  **Recommendation:** The **CatBoost** model is recommended for deployment due to its superior ability to rank risky companies (highest ROC-AUC) while remaining computationally efficient.