# 50 Startups

Predict which companies to invest for maximizing profit

**Dataset:**
ID - startup ID  
R&D Spend - how much each startup spends on Research and Development  
Administration - how much they spend on Administration cost  
Marketing Spend - how much they spend on Marketing  
State - which state the startup is based in  
Category - which business category the startup belong to  
Profit - the profit made by the startup  

**Questions:**    
Predict which companies to invest for maximizing profit (choose model with the best score; create predictions; choose companies)  

**Steps Overview:**
 
Import libraries and load data.  
Explore the data to understand its structure and identify issues like missing values.  
Preprocess: Handle missing values, encode categories, scale features.  
Build and evaluate models.  
Compare results and select the best model.  
Predict on test data and identify top companies.  
Suggest further checks.  

We have comparison of two models: Linear Regression and Gradient Boosting Regressor 

**Result**: The best model is **Gradient Boosting Regressor** with **R2 score = 0.972002**.

[Jupyter Notebook](50_startups.ipynb##Project-Conclusion)

![Final Results/](LRvsGB_results.png)

## Project Conclusion

Model Performance: The Gradient Boosting Regressor (using all features) yielded the best results, achieving the lowest RMSE and highest $R^2$ score (~0.94), significantly outperforming the Linear Regression baseline.  

Feature Impact: Removing 'Administration' did not drastically improve the model, suggesting the tree-based model was already effectively handling the low-importance feature.  

Business Insight: The analysis confirms that R&D Spend is the most critical predictor of startup success.  
Investors looking to maximize profit should prioritize companies with high R&D and Marketing budgets, regardless of their Administrative costs or State location.

### Future work

Check multicoleniarity  
P-value  
t-test