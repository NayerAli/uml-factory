/**
 * Un porte-monnaie abstrait pouvant contenir de l'argent.
 */
public abstract class Wallet {

    private double amount;

    public Wallet() {
    }

    public double getAmount() {
        return amount;
    }

    public void setAmount(double amount) {
        this.amount = amount;
    }

    /**
     * Ajoute de l'argent au porte-monnaie.
     * TODO: préciser le montant à ajouter (opération sans paramètre dans le diagramme).
     */
    public void addMoney() {
        // TODO: implémenter l'ajout d'argent
    }
}
