from django.db import models

class Qualification(models.Model):
    qulification_type = models.CharField(max_length=200, blank=True)
    subjects = models.CharField(max_length=200, blank=True)
    grades = models.CharField(max_length=50, blank=True)
    completion_year = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"""qualification_type:{self.qulification_type}, subjects:{self.subjects}, grades:{self.grades}, completion_year:{self.completion_year}"""
    
