from datetime import timedelta, datetime
from flask import Flask, render_template, request, redirect, url_for
import mysql.connector

import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Temporary placeholder: every action belongs to user 1 until we add login.
# When login is added, only this one idea needs to change.
CURRENT_USER_ID = 1

# MySQL connection
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        use_pure=True
    )

# Homepage
@app.route('/')
def home():
    return render_template('index.html')

# Browse Recipes (with search and filters)
@app.route('/recipes')
def recipes():

    connection = None
    cursor = None

    # Read the values the form sent (default to empty / "All" / "Any")
    search = request.args.get('search', '').strip()
    difficulty = request.args.get('difficulty', 'All')
    max_time = request.args.get('max_time', 'Any')

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Start with a query that matches every recipe,
        # then add conditions only if the user chose a search or filter
        query = "SELECT * FROM Recipes WHERE 1=1"
        values = []

        if search != '':
            # Match the recipe name, OR any ingredient of the recipe.
            # The % signs mean "any text before/after", so "piz" finds "Pizza".
            query += """
                AND (recipe_name LIKE %s
                     OR recipe_id IN (SELECT recipe_id FROM Ingredients
                                      WHERE ingredient_name LIKE %s))
            """
            pattern = '%' + search + '%'
            values.append(pattern)
            values.append(pattern)

        if difficulty != 'All':
            query += " AND difficulty = %s"
            values.append(difficulty)

        if max_time != 'Any':
            query += " AND cooking_time <= %s"
            values.append(int(max_time))

        cursor.execute(query, values)
        recipes = cursor.fetchall()

        # We also send search/difficulty/max_time back, so the form
        # still shows what the user chose
        return render_template('recipes.html',
                               recipes=recipes,
                               search=search,
                               difficulty=difficulty,
                               max_time=max_time)

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Recipe Details (one recipe + its ingredients + favorite status)
@app.route('/recipe/<int:recipe_id>')
def recipe_detail(recipe_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # JOIN brings in the author's name from the Users table
        cursor.execute("""
            SELECT Recipes.*, Users.name AS author
            FROM Recipes
            LEFT JOIN Users ON Recipes.user_id = Users.user_id
            WHERE Recipes.recipe_id = %s
        """, (recipe_id,))
        recipe = cursor.fetchone()

        # If nobody has this recipe_id, show a message instead of crashing
        if recipe is None:
            return "Recipe not found.", 404

        # Get the ingredients that belong to this recipe
        cursor.execute("""
            SELECT ingredient_name, quantity
            FROM Ingredients
            WHERE recipe_id = %s
        """, (recipe_id,))
        ingredients = cursor.fetchall()

        # Is this recipe already in the user's favorites?
        cursor.execute("""
            SELECT 1 FROM Favorites
            WHERE user_id = %s AND recipe_id = %s
        """, (CURRENT_USER_ID, recipe_id))
        is_favorite = cursor.fetchone() is not None

        return render_template('recipe_detail.html',
                               recipe=recipe,
                               ingredients=ingredients,
                               is_favorite=is_favorite)

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# View all favorites of the current user
@app.route('/favorites')
def favorites():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # JOIN: Favorites only stores ids, so we join Recipes to get the details
        cursor.execute("""
            SELECT Recipes.*
            FROM Favorites
            JOIN Recipes ON Favorites.recipe_id = Recipes.recipe_id
            WHERE Favorites.user_id = %s
            ORDER BY Favorites.favorite_id DESC
        """, (CURRENT_USER_ID,))
        favorite_recipes = cursor.fetchall()

        return render_template('favorites.html', recipes=favorite_recipes)

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Add a recipe to favorites (called when the button is clicked)
@app.route('/favorite/<int:recipe_id>/add', methods=['POST'])
def add_favorite(recipe_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # INSERT IGNORE: if this recipe is already a favorite,
        # MySQL skips it quietly instead of giving a duplicate error
        cursor.execute("""
            INSERT IGNORE INTO Favorites (user_id, recipe_id)
            VALUES (%s, %s)
        """, (CURRENT_USER_ID, recipe_id))
        connection.commit()

        return redirect(url_for('favorites'))

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Remove a recipe from favorites
@app.route('/favorite/<int:recipe_id>/remove', methods=['POST'])
def remove_favorite(recipe_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            DELETE FROM Favorites
            WHERE user_id = %s AND recipe_id = %s
        """, (CURRENT_USER_ID, recipe_id))
        connection.commit()

        return redirect(url_for('favorites'))

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Meal Planner: show the user's latest plan, one card per day
@app.route('/meal-planner')
def meal_planner():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Take the user's most recent plan (latest start date)
        cursor.execute("""
            SELECT * FROM Meal_Plans
            WHERE user_id = %s
            ORDER BY start_date DESC
            LIMIT 1
        """, (CURRENT_USER_ID,))
        plan = cursor.fetchone()

        days = []
        all_recipes = []

        if plan:
            # JOIN: Meal_Plan_Items only stores ids, so we join Recipes for the names.
            # FIELD(...) sorts meals in a sensible order within a day.
            cursor.execute("""
                SELECT Meal_Plan_Items.item_id, Meal_Plan_Items.meal_date,
                       Meal_Plan_Items.meal_type,
                       Recipes.recipe_id, Recipes.recipe_name
                FROM Meal_Plan_Items
                JOIN Recipes ON Meal_Plan_Items.recipe_id = Recipes.recipe_id
                WHERE Meal_Plan_Items.plan_id = %s
                ORDER BY Meal_Plan_Items.meal_date,
                         FIELD(Meal_Plan_Items.meal_type, 'Breakfast', 'Lunch', 'Dinner', 'Snack')
            """, (plan['plan_id'],))
            items = cursor.fetchall()

            # All recipes, for the "Add a Meal" dropdown
            cursor.execute("SELECT recipe_id, recipe_name FROM Recipes ORDER BY recipe_name")
            all_recipes = cursor.fetchall()

            # Build one entry for every date from start_date to end_date
            number_of_days = (plan['end_date'] - plan['start_date']).days + 1
            number_of_days = max(1, min(number_of_days, 31))   # safety limit

            for i in range(number_of_days):
                day_date = plan['start_date'] + timedelta(days=i)
                days.append({
                    'date': day_date.isoformat(),   # like 2026-11-16, used by the form
                    'label': day_date.strftime('%A, %d %b %Y'),
                    'meals': [item for item in items if item['meal_date'] == day_date]
                })

        return render_template('meal_planner.html',
                               plan=plan, days=days, all_recipes=all_recipes)

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Add a meal to the plan (called when the "Add Meal" form is submitted)
@app.route('/meal-planner/add', methods=['POST'])
def add_meal():

    # Read what the form sent
    plan_id = request.form.get('plan_id', '')
    recipe_id = request.form.get('recipe_id', '')
    meal_date_text = request.form.get('meal_date', '')
    meal_type = request.form.get('meal_type', '')

    # Check the data before saving it
    if not plan_id.isdigit() or not recipe_id.isdigit():
        return "Invalid plan or recipe.", 400

    if meal_type not in ('Breakfast', 'Lunch', 'Dinner', 'Snack'):
        return "Invalid meal type.", 400

    try:
        meal_date = datetime.strptime(meal_date_text, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date.", 400

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # The plan must belong to the current user
        cursor.execute("""
            SELECT * FROM Meal_Plans
            WHERE plan_id = %s AND user_id = %s
        """, (int(plan_id), CURRENT_USER_ID))
        plan = cursor.fetchone()

        if plan is None:
            return "Meal plan not found.", 404

        # The date must be inside the plan's date range
        if meal_date < plan['start_date'] or meal_date > plan['end_date']:
            return "That date is outside this meal plan.", 400

        # The recipe must exist
        cursor.execute("SELECT 1 FROM Recipes WHERE recipe_id = %s", (int(recipe_id),))
        if cursor.fetchone() is None:
            return "Recipe not found.", 404

        cursor.execute("""
            INSERT INTO Meal_Plan_Items (plan_id, recipe_id, meal_date, meal_type)
            VALUES (%s, %s, %s, %s)
        """, (int(plan_id), int(recipe_id), meal_date, meal_type))
        connection.commit()

        return redirect(url_for('meal_planner'))

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Remove one meal from the plan
@app.route('/meal-planner/remove/<int:item_id>', methods=['POST'])
def remove_meal(item_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # JOIN inside DELETE: only delete the item if its plan belongs to this user
        cursor.execute("""
            DELETE Meal_Plan_Items
            FROM Meal_Plan_Items
            JOIN Meal_Plans ON Meal_Plan_Items.plan_id = Meal_Plans.plan_id
            WHERE Meal_Plan_Items.item_id = %s AND Meal_Plans.user_id = %s
        """, (item_id, CURRENT_USER_ID))
        connection.commit()

        return redirect(url_for('meal_planner'))

    except mysql.connector.Error as error:
        return f"MySQL Database Error: {error}", 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# Add Recipe (shows the form, and saves recipe + ingredients when submitted)
@app.route('/add-recipe', methods=['GET', 'POST'])
def add_recipe():

    error = None
    ingredient_rows = [('', '')]   # first visit: one empty ingredient row

    if request.method == 'POST':

        # Read what the user typed in the form
        recipe_name = request.form.get('recipe_name', '').strip()
        description = request.form.get('description', '').strip()
        cooking_time = request.form.get('cooking_time', '').strip()
        difficulty = request.form.get('difficulty', 'Easy')
        instructions = request.form.get('instructions', '').strip()

        # The form can have many ingredient rows, so we read them as lists
        names = request.form.getlist('ingredient_name')
        quantities = request.form.getlist('quantity')

        # Keep what the user typed, so we can show it again if there is an error
        ingredient_rows = list(zip(names, quantities)) or [('', '')]

        # Keep only rows where an ingredient name was typed
        ingredients_to_save = []
        for name, qty in zip(names, quantities):
            name = name.strip()
            qty = qty.strip()
            if name != '':
                ingredients_to_save.append((name, qty if qty != '' else None))

        # Check the data before saving it
        if recipe_name == '':
            error = "Recipe name is required."
        elif not cooking_time.isdigit() or int(cooking_time) < 1:
            error = "Cooking time must be a whole number of minutes (1 or more)."
        elif difficulty not in ('Easy', 'Medium', 'Hard'):
            error = "Please choose a valid difficulty."
        else:
            connection = None
            cursor = None

            try:
                connection = get_db_connection()
                cursor = connection.cursor()

                # 1) Save the recipe (owner = the current placeholder user)
                cursor.execute("""
                    INSERT INTO Recipes
                    (user_id, recipe_name, description, cooking_time, difficulty, instructions)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (CURRENT_USER_ID, recipe_name, description, int(cooking_time), difficulty, instructions))

                # MySQL gave this new recipe a number. We need it to link the ingredients.
                new_recipe_id = cursor.lastrowid

                # 2) Save every ingredient, linked to the new recipe
                if ingredients_to_save:
                    rows = [(new_recipe_id, name, qty) for name, qty in ingredients_to_save]
                    cursor.executemany("""
                        INSERT INTO Ingredients (recipe_id, ingredient_name, quantity)
                        VALUES (%s, %s, %s)
                    """, rows)

                # One commit at the end: either everything is saved, or nothing is
                connection.commit()

                # Go straight to the new recipe's details page
                return redirect(url_for('recipe_detail', recipe_id=new_recipe_id))

            except mysql.connector.Error as e:
                if connection:
                    connection.rollback()   # undo anything half-saved
                error = f"MySQL Database Error: {e}"

            finally:
                if cursor:
                    cursor.close()

                if connection and connection.is_connected():
                    connection.close()

    # On first visit (GET) or when there is an error, show the form
    return render_template('add_recipe.html',
                           error=error,
                           form=request.form,
                           ingredient_rows=ingredient_rows)

if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)