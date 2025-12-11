## Classification of the Quality of Portuguese White Wines  
    
**Goal of the Project**  
Predict wine quality in advance — using physicochemical characteristics, without relying on tasting. 

**Who Needs This**  

**1) Winemakers:**   
• identify promising batches early;  
• decide on processing, blending, or aging.  
**2) Buyers, sommeliers, distributors:**   
• build a reliable and diverse assortment;  
• avoid purchasing low-quality batches.  
**Both types of errors are costly:**   
• missing a good wine = lost profit;   
• accepting a poor wine as good = quality risks and financial losses.   
➡ The model must classify **both classes equally accurately**, without favoring one over the other.  

**Evaluation metrics**
Therefore, **F1-score** (which controls the balance of Precision and Recall in the case of class imbalance)  
and **PR-AUC** (which shows the stability of the model when an important class is selected and works more reliably than Accuracy on unbalanced data)  
are chosen to evaluate the model.

[Jupyter Notebook](Classification_Portuguese_Wines.ipynb##The-Final)

![Final Results/](Final_results.png)

#### The final Conclusion 
**The final Ensemble** model proves to be the most robust solution, effectively leveraging the complementary strengths of Gradient Boosting and KNN. 
It *achieves the highest* overall PR-AUC score (~0.833) and F1-score (~0.714), providing the best trade-off between identifying good wines (Recall) and minimizing false positives (Precision).  
The confusion matrix confirms it correctly identifies a significant portion of the minority class while maintaining high accuracy on the majority class.    
This demonstrates the power of ensemble methods in leveraging diverse model predictions to improve overall robustness and accuracy.  
The final model is ready for deployment, with the Voting Classifier being the recommended choice due to its balanced and strong performance across key metrics for our imbalanced classification task.

However, while the **Ensemble** offers peak performance, the **tuned KNN** model remains a compelling alternative due to its simplicity, lower training costs, and ease of deployment.
In contrast, the **Ensemble model**, though more performant, requires maintaining multiple models, more memory, and longer inference times. 

**The final choice** between these models should weigh the marginal performance gains of the Ensemble against  
the increased complexity, training time, and economic costs associated with implementing and maintaining such a sophisticated system.

------------------------------------------------

#### Future steps:   
deploy with **SHAP** for interpretability, monitor drift on new vintages, or incorporate external factors like _region_ for enhanced accuracy.  
Compare feature importances – if alcohol, volatile-acidity, sulphates are on top we confirm wine-expert knowledge.  
re-check calibration plot – business may prefer a well-calibrated prob-0.7 over a 0.9 that is wrong half the time.  
Probability threshold 0.5 can be moved later to favour precision or recall depending on business cost.  
GB usually beats RF on tabular data, but watch for over-fit; use **validation_fraction** early-stop

------------------------------------------------

#### Once I find data about Georgian wines, I'll be able to taste them myself!