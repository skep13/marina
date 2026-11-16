from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_LINE_SPACING
from pathlib import Path
src='/Users/jacobmatthews/Downloads/Relational_Database_Transfer_Worksheet.docx'
d=Document(src)
ps=list(d.paragraphs)
fills={8:['primary','foreign','referential'],9:['one to many','many to many','event'],10:['Long Integer','Short Text','Date/Time'],11:['foreign','Appointment','referential']}
for i, words in fills.items():
 for r in ps[i].runs:
  for word in words[:]:
   if '______' in r.text:
    r.text=r.text.replace('______',word,1); words.remove(word)
answers={
16:'StudentName is not unique because two students can share a name, and a name can change. StudentID gives each student a unique, stable identifier. An AutoNumber does not prevent the same person being entered twice with different IDs.',
21:'No. The StudentID and LaptopID pair would repeat for all three loans, violating primary-key uniqueness. Use LoanID as an AutoNumber primary key, with StudentID and LaptopID as foreign keys; each borrowing event then has its own record.',
26:'A Student can have zero to many Loans. Each Loan must link to exactly one Student, so its minimum and maximum are both one. Set Loan.StudentID to Required (not null) and enforce referential integrity; the foreign-key constraint alone would still allow a null value.',
31:'Laptop to Loan is one to many across time: one laptop can appear in many historical loans, while each loan concerns one laptop. Add a rule preventing more than one active loan for the same laptop. Record DateReturned and reject a new loan while an existing loan for that laptop has no return date.',
39:'Update anomaly: changing a student’s email requires changing every loan row, and missed rows leave conflicting emails. Deletion anomaly: deleting the student’s last loan could remove their only stored contact details. Store student details once in Student and model details once in Laptop; Loan stores their foreign keys, so deleting a loan does not delete those records.',
44:'LoanID determines StudentID, and StudentID determines Email, so Email would depend transitively on LoanID through a non-key attribute. This violates third normal form and duplicates student data. Keep Email in Student and join Loan.StudentID to Student.StudentID in a query to display it alongside loan details.',
49:'This is a referential-integrity failure: the loan references a student who does not exist. Enforce the foreign-key relationship between Loan.StudentID and Student.StudentID. It checks that the ID exists, but cannot establish whether that existing student was the actual borrower; user verification is still needed.',
54:'Set a Loan record validation rule: [DateDue] >= [DateBorrowed], with both dates required. Set Laptop.AssetNumber to Required and Indexed: Yes (No Duplicates). The relationships check that referenced students and laptops exist; they do not compare dates or enforce uniqueness of AssetNumber.',
62:'Aisha (StudentID 1) links to LoanIDs 1 and 2. LT-101 (LaptopID 1) links to LoanIDs 1 and 3. The first result shows one Student linked to multiple Loans; the second shows one Laptop linked to multiple Loans. Each loan has one student and one laptop.',
67:'Use Student, Loan and Laptop. Join Student.StudentID = Loan.StudentID and Laptop.LaptopID = Loan.LaptopID. Output Student.StudentName, Laptop.AssetNumber and Loan.DateDue. Joining StudentID to LaptopID would compare unrelated identifiers; matching numbers do not show who borrowed a laptop.',
72:'Use both conditions together: [DateDue] < [CheckDate] AND [DateReturned] Is Null. In Access, define CheckDate as a Date/Time query parameter. DateDue alone is insufficient because a loan with a past due date may already have been returned; it is not currently overdue.',
77:'Valid repeat: add a new LoanID with StudentID 1, LaptopID 1, DateBorrowed 23/10/2026 and DateDue 30/10/2026 after the previous loan has ended; accept it. Invalid FK: StudentID 999, LaptopID 1, borrowed 23/10/2026, due 30/10/2026; reject because Student 999 does not exist. Invalid dates: StudentID 1, LaptopID 2, borrowed 23/10/2026, due 22/10/2026; reject because the due date precedes borrowing.',
85:'Booking.MemberID references Member.MemberID, and Booking.ClassID references Class.ClassID. Store BookingDateTime in Booking because it records when that particular member made that particular booking. It describes the booking event, rather than the member or the class generally.',
90:'Create OrderLine(OrderLineID PK, OrderID FK, ProductID FK, Quantity, PriceCharged). OrderID references Order and ProductID references Product. Quantity is the amount of that product in that order. PriceCharged is the unit price agreed for that order line, preserving the sale price even if the product’s current price later changes.',
95:'LearnerID plus CourseID would repeat when the learner takes the course in another year. Use Enrolment(EnrolmentID PK, LearnerID FK, CourseID FK, AcademicYear), with a unique constraint on (LearnerID, CourseID, AcademicYear). This assumes at most one enrolment per learner per course per academic year; if multiple attempts in a year are allowed, include an offering or attempt identifier instead.',
100:'Restricting deletion blocks removal of a Student while related Loan rows exist. Cascading deletion removes the Student and all their related Loans, losing borrowing history. Restrict deletion and mark former students inactive instead, retaining their IDs and loan records. This preserves history and prevents orphaned loans.'}
for i,a in answers.items():
 p=ps[i];p.text=a;p.paragraph_format.line_spacing=1.1;p.paragraph_format.space_after=Pt(12)
 for r in p.runs:r.font.size=Pt(11)
 for j in range(i+1,i+4):
  e=ps[j]._element;e.getparent().remove(e)
for p in d.paragraphs:
 if p.text.startswith('Q'): p.paragraph_format.keep_with_next=True
for name in ['Title','Heading 1','Heading 2']:
 d.styles[name].font.color.rgb=RGBColor(0,0,0)
for p in d.paragraphs:
 if p.style.name.startswith('Heading') or p.style.name=='Title':
  for r in p.runs:r.font.color.rgb=RGBColor(0,0,0)
out='/Users/jacobmatthews/marina/output/Relational_Database_Transfer_Worksheet_Completed.docx'
d.save(out)
print(out)
